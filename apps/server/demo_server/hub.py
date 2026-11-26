"""Connections, fan-out, and presence, all in memory.

- One fan-out: an alert goes to every connected device of every eligible account in one pass, so
  students and parents get it at the same moment. Drills and replays: test accounts only.
- Live location exists only here, only while sharing is on AND a linked parent's screen is open;
  it is dropped the moment either stops. Never stored, never logged.
- A student sees who is checking in (the label they know, e.g. "Mom") only inside the app; no
  notification, no counts, no history.
"""

import asyncio
import hashlib
import logging
import math
import secrets
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

from campus_safety import events
from campus_safety.alerts.rules import Draft
from campus_safety.official.alerts import OfficialAlert
from demo_server import signing
from demo_server.area import area_for
from demo_server.mailbox import MailboxChannel
from demo_server.store import Account, Store
from demo_server.threads import Threads

SHARING = ("on", "paused", "off")
CLIENTS = ("web", "ios")
BAND_TIMEOUT_S = 60.0  # no answer by then: "couldn't reach the phone", never "away"
OK_TIMEOUT_S = 600.0  # "Are you OK?": the parent hears "No answer yet" only after 10 minutes
OK_FORGET_AFTER = 6  # an unanswered nudge is forgotten after 6 x the timeout (an hour)
OK_ANSWERS = ("ok", "call_me", "off")
CHECK_IN_STATES = ("safe", "sheltering")
# Same fixed list as SHELTER_PLACES in apps/*/src/shared/api.ts (no free text, so no names).
SHELTER_PLACES = ("my room", "a campus building", "a friend's place", "the library", "off campus")

log = logging.getLogger(__name__)


class Peer(Protocol):
    async def send_json(self, data: Any, mode: str = "text") -> None: ...


@dataclass
class Clock:
    """The demo clock: live, or moved to a late night / event night so windows are active."""

    offset: timedelta = timedelta(0)
    event_night: bool = False
    nights: frozenset[date] = field(default_factory=events.event_nights)

    def now(self) -> datetime:
        return datetime.now(events.LOCAL) + self.offset

    def set(self, preset: str) -> None:
        real = datetime.now(events.LOCAL)
        if preset == "live":
            self.offset, self.event_night = timedelta(0), False
            return
        target = datetime.combine(real.date(), time(23, 45), events.LOCAL)
        self.offset, self.event_night = target - real, preset == "event_night"

    def windows(self) -> list[str]:
        now = self.now()
        nights = self.nights | {events.night_of(now)} if self.event_night else self.nights
        active = []
        if events.is_late_night(now):
            active.append("late_night")
        if events.is_event_night(now, nights):
            active.append("event_night")
        return active

    def state(self) -> dict[str, Any]:
        return {
            "now": self.now().isoformat(timespec="seconds"),
            "live": self.offset == timedelta(0),
            "windows": self.windows(),
        }


def _coordinate(value: object, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and abs(number) <= limit else None


class Hub:
    def __init__(self, store: Store, clock: Clock, segment_names: dict[str, str]) -> None:
        self.store = store
        self.clock = clock
        self._segments = segment_names
        self._peers: dict[str, set[Peer]] = defaultdict(set)
        self._accounts: dict[str, Account] = {}
        self._sharing: dict[str, str] = {}
        self._location: dict[str, dict[str, Any]] = {}
        self.threads = Threads()
        self._live: dict[str, bool] = {}  # open thread id -> test accounts only
        self._check_ins: dict[str, dict[str, dict[str, Any]]] = {}  # thread -> student -> check-in
        self._followups: dict[str, str] = {}  # engine thread id -> last kind sent
        # Parent check-ins (v8): request id -> (parent, student). Memory only, dropped on answer.
        self._band: dict[str, tuple[str, str]] = {}
        self._timers: set[asyncio.Task[None]] = set()
        self.band_timeout = BAND_TIMEOUT_S
        self.verifier = signing.Verifier()
        self._ok: dict[str, tuple[str, str]] = {}  # "Are you OK?" id -> (parent, student)
        self.ok_timeout = OK_TIMEOUT_S
        self._arrived: set[tuple[str, date]] = set()  # (student, night): "Arrived home" sent
        self._band_outcomes: Counter[str] = Counter()  # counts only, for the console
        self._ok_outcomes: Counter[str] = Counter()

    def online(self, account_id: str) -> bool:
        return bool(self._peers.get(account_id))

    def viewers(self, student_id: str) -> list[str]:
        parents = self.store.parents_of(student_id)
        return sorted(label for parent, label in parents.items() if self.online(parent))

    def sharing(self, student_id: str) -> str:
        return self._sharing.get(student_id, "off")

    def has_location(self, student_id: str) -> bool:
        return student_id in self._location

    async def join(self, account: Account, peer: Peer) -> None:
        first = not self.online(account.id)
        self._peers[account.id].add(peer)
        self._accounts[account.id] = account
        await self._safe(peer, self.hello(account))
        if account.role == "parent" and first:
            await self._viewers_changed(account.id)

    async def leave(self, account: Account, peer: Peer) -> None:
        peers = self._peers.get(account.id, set())
        peers.discard(peer)
        if not peers:
            self._peers.pop(account.id, None)
            if account.role == "parent":
                await self._viewers_changed(account.id)

    def hello(self, account: Account) -> dict[str, Any]:
        message: dict[str, Any] = {
            "type": "hello",
            "account": {"id": account.id, "role": account.role, "name": account.display_name},
            "clock": self.clock.state(),
        }
        if account.role == "student":
            message["viewers"] = self.viewers(account.id)
            message["sharing"] = self.sharing(account.id)
            message["check_ins"] = self._check_ins_of({account.id})
            key = self.store.take_undelivered_key(account.id)
            if key:  # once per key, over the student's own authenticated socket
                message["signing"] = {"key_id": key[0], "secret": key[1], "label": signing.LABEL}
        elif account.role == "parent":
            students = self.store.students_of(account.id)
            message["students"] = [self._student(s) for s in students]
            message["check_ins"] = self._check_ins_of(set(students))
        return message

    def check_ins(self, thread_id: str) -> list[dict[str, Any]]:
        return list(self._check_ins.get(thread_id, {}).values())

    def _check_ins_of(self, students: set[str]) -> list[dict[str, Any]]:
        return [c for by in self._check_ins.values() for s, c in by.items() if s in students]

    def _student(self, student_id: str) -> dict[str, Any]:
        account = self.store.account(student_id)
        return {
            "id": student_id,
            "name": account.display_name if account else student_id,
            "sharing": self.sharing(student_id),
            "location": self._location.get(student_id),
        }

    async def message(self, account: Account, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == "ack" and data.get("client") in CLIENTS:
            await self._ack(account, str(data.get("alert_id")), str(data["client"]))
        elif account.role != "student":
            return
        elif kind == "location":
            await self._location_update(account, data)
        elif kind == "sharing" and data.get("state") in SHARING:
            await self._set_sharing(account, str(data["state"]))
        elif kind == "heads_up" and data.get("segment_id") in self._segments:
            await self._heads_up(account, str(data["segment_id"]))
        elif kind == "check_in":
            await self._check_in(account, data)
        elif kind == "band_answer":
            await self._band_answer(account, data)
        elif kind == "ok_answer":
            await self._ok_answer(account, data)
        elif kind == "arrived_home":
            await self._arrived_home(account)

    def reassurance_counts(self) -> dict[str, dict[str, int]]:
        """Outcomes since the server started: counts only, never who, where or a band."""
        return {
            "check_ins": dict(self._band_outcomes),
            "are_you_ok": dict(self._ok_outcomes),
            "arrived_home": {"sent": len(self._arrived)},
        }

    def pending_ok_requests(self) -> int:
        return len(self._ok)

    def _later(self, work: Any) -> None:
        timer = asyncio.create_task(work)
        self._timers.add(timer)
        timer.add_done_callback(self._timers.discard)

    async def ask_ok(self, parent: Account, student_id: str) -> str | None:
        """ "Are you OK?" goes to the student only; the parent hears the answer, or "No answer yet"
        after ok_timeout. None when the parent is not linked."""
        label = self.store.parents_of(student_id).get(parent.id)
        if parent.role != "parent" or label is None:
            return None
        request_id = secrets.token_hex(8)
        self._ok[request_id] = (parent.id, student_id)
        await self._send(
            student_id, {"type": "ok_request", "request_id": request_id, "from": label}
        )
        self._later(self._ok_expire(request_id))
        return request_id

    async def _ok_expire(self, request_id: str) -> None:
        await asyncio.sleep(self.ok_timeout)
        entry = self._ok.get(request_id)
        if entry:
            await self._ok_result(entry, request_id, "no_answer")
            await asyncio.sleep(self.ok_timeout * (OK_FORGET_AFTER - 1))
            self._ok.pop(request_id, None)

    async def _ok_answer(self, student: Account, data: dict[str, Any]) -> None:
        request_id, answer = data.get("request_id"), data.get("answer")
        entry = self._ok.get(request_id) if isinstance(request_id, str) else None
        if entry is None or entry[1] != student.id or answer not in OK_ANSWERS:
            return
        del self._ok[str(request_id)]
        await self._ok_result(entry, str(request_id), str(answer))

    async def _ok_result(self, entry: tuple[str, str], request_id: str, state: str) -> None:
        message = {
            "type": "ok_result",
            "request_id": request_id,
            "student_id": entry[1],
            "state": state,
        }
        await self._send(entry[0], message)
        self._ok_outcomes[state] += 1
        log.info("are-you-ok %s", state)

    def pending_band_requests(self) -> int:
        return len(self._band)

    async def request_band(self, parent: Account, student_id: str) -> str | None:
        """A linked parent asks for the student's band. None when they are not linked. The phone
        answers on its own; a phone that is offline or silent is "unreachable"."""
        label = self.store.parents_of(student_id).get(parent.id)
        if parent.role != "parent" or label is None:
            return None
        request_id = secrets.token_hex(8)
        if not self.online(student_id):
            await self._band_result(parent.id, student_id, request_id, "unreachable")
            return request_id
        self._band[request_id] = (parent.id, student_id)
        await self._send(
            student_id, {"type": "band_request", "request_id": request_id, "from": label}
        )
        self._later(self._band_expire(request_id))
        return request_id

    async def _band_expire(self, request_id: str) -> None:
        await asyncio.sleep(self.band_timeout)
        entry = self._band.pop(request_id, None)
        if entry:
            await self._band_result(entry[0], entry[1], request_id, "unreachable")

    async def _band_answer(self, student: Account, data: dict[str, Any]) -> None:
        request_id = data.get("request_id")
        entry = self._band.get(request_id) if isinstance(request_id, str) else None
        if entry is None or entry[1] != student.id:
            return
        del self._band[str(request_id)]
        if data.get("declined") is True:
            await self._band_result(entry[0], student.id, str(request_id), "declined")
            return
        band, at, signature = data.get("band"), data.get("answered_at"), data.get("signature")
        key = self.store.device_key(student.id)
        ok = (
            key is not None
            and all(isinstance(v, str) for v in (band, at, signature))
            and self.verifier.check(
                key[1], str(request_id), str(band), str(at), str(signature), datetime.now(UTC)
            )
        )
        if ok:
            extra = {"band": band, "answered_at": at}
            await self._band_result(entry[0], student.id, str(request_id), "answered", extra)
        else:
            await self._band_result(entry[0], student.id, str(request_id), "unverified")

    async def _band_result(
        self,
        parent_id: str,
        student_id: str,
        request_id: str,
        state: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        message = {
            "type": "band_result",
            "request_id": request_id,
            "student_id": student_id,
            "state": state,
            **(extra or {}),
        }
        await self._send(parent_id, message)
        self._band_outcomes[state] += 1
        log.info("check-in request %s", state)  # the state only: never who, where or the band

    async def _check_in(self, student: Account, data: dict[str, Any]) -> None:
        """Private "I'm safe" / "I'm sheltering at <place>": linked parents only, memory only,
        only on a live thread the student could receive; anything else is ignored."""
        thread_id, state, place = data.get("thread_id"), data.get("state"), data.get("place")
        test_only = self._live.get(thread_id) if isinstance(thread_id, str) else None
        if test_only is None or (test_only and not student.is_test):
            return
        if state not in CHECK_IN_STATES or (state == "sheltering") != (place in SHELTER_PLACES):
            return
        check_in = {
            "thread_id": thread_id,
            "student_id": student.id,
            "student_name": student.display_name,
            "state": state,
            "place": place if state == "sheltering" else None,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._check_ins.setdefault(str(thread_id), {})[student.id] = check_in
        update = {"type": "check_in", "check_in": check_in}
        await self._to_parents(student.id, update)
        await self._send(student.id, update)
        parents = self.store.parents_of(student.id)
        devices = sum(len(self._peers.get(a, ())) for a in [student.id, *parents])
        log.info("check-in relayed to %d devices", devices)

    async def _close_thread(self, thread_id: str) -> None:
        self._live.pop(thread_id, None)
        students = self._check_ins.pop(thread_id, {})
        cleared = {"type": "check_in_cleared", "thread_id": thread_id}
        for student_id in students:
            await self._to_parents(student_id, cleared)
            await self._send(student_id, cleared)

    async def _location_update(self, student: Account, data: dict[str, Any]) -> None:
        lat, lon = _coordinate(data.get("lat"), 90), _coordinate(data.get("lon"), 180)
        if lat is None or lon is None:
            return
        if self.sharing(student.id) != "on" or not self.viewers(student.id):
            self._location.pop(student.id, None)
            return
        point = {"lat": lat, "lon": lon, "at": datetime.now(UTC).isoformat(timespec="seconds")}
        self._location[student.id] = point
        await self._to_parents(student.id, {"type": "location", "student_id": student.id, **point})

    async def _arrived_home(self, student: Account) -> None:
        """On an event night, a sharing student's phone reached its home area (the phone decides,
        with the student's switch on): sharing ends and linked parents hear "Arrived home" once."""
        night = events.night_of(self.clock.now())
        if (
            "event_night" not in self.clock.windows()
            or self.sharing(student.id) != "on"
            or (student.id, night) in self._arrived
        ):
            return
        self._arrived.add((student.id, night))
        await self._set_sharing(student, "off")
        message = {
            "type": "arrived_home",
            "student_id": student.id,
            "student_name": student.display_name,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        await self._to_parents(student.id, message)
        log.info("arrived home sent")

    async def _set_sharing(self, student: Account, state: str) -> None:
        previous = self.sharing(student.id)
        self._sharing[student.id] = state
        if state != "on":
            self._location.pop(student.id, None)
        if state != previous:
            update = {"type": "sharing", "student_id": student.id, "state": state}
            await self._to_parents(student.id, update)

    async def _heads_up(self, student: Account, segment_id: str) -> None:
        if self.sharing(student.id) != "on":
            return  # the student got the heads-up on the phone; parents only if sharing
        await self._to_parents(
            student.id,
            {
                "type": "heads_up",
                "student_id": student.id,
                "student_name": student.display_name,
                "segment_id": segment_id,
                "segment_name": self._segments[segment_id],
            },
        )

    async def _ack(self, account: Account, alert_id: str, client: str) -> None:
        self.store.delivered(alert_id, account.id, client, datetime.now(UTC))
        consoles = [a for a, acc in self._accounts.items() if acc.role == "console"]
        for console in consoles:
            await self._send(console, {"type": "latency"})

    async def _viewers_changed(self, parent_id: str) -> None:
        for student in self.store.students_of(parent_id):
            labels = self.viewers(student)
            if not labels:
                self._location.pop(student, None)
            await self._send(student, {"type": "viewers", "labels": labels})

    async def _to_parents(self, student_id: str, data: dict[str, Any]) -> None:
        for parent in self.store.parents_of(student_id):
            await self._send(parent, data)

    async def _send(self, account_id: str, data: dict[str, Any]) -> None:
        for peer in list(self._peers.get(account_id, ())):
            await self._safe(peer, data)

    async def _safe(self, peer: Peer, data: dict[str, Any]) -> None:
        try:
            await peer.send_json(data)
        except Exception:  # a closed socket must not stop the fan-out
            for peers in self._peers.values():
                peers.discard(peer)

    async def notes_changed(self, thread_id: str) -> None:
        """Every open screen refetches the thread's notes (the message carries no note)."""
        peers = [peer for peers in self._peers.values() for peer in peers]
        message = {"type": "notes_changed", "thread_id": thread_id}
        await asyncio.gather(*(self._safe(p, message) for p in peers))

    async def set_clock(self, preset: str) -> dict[str, Any]:
        self.clock.set(preset)
        state = self.clock.state()
        peers = [peer for peers in self._peers.values() for peer in peers]
        await asyncio.gather(*(self._safe(p, {"type": "clock", "clock": state}) for p in peers))
        return state

    async def publish_followup(
        self, incident_id: str, kind: str, draft: Draft, recipients: Sequence[str]
    ) -> bool:
        """An engine alert (IU crime log or two-outlet news) and its correction or all-clear, on one
        card (thread incident-<id>) for every recipient and in their mailbox. Order is enforced:
        nothing before the alert, nothing after the all-clear. IU's own alerts use publish()."""
        thread_id = f"incident-{incident_id}"
        last = self._followups.get(thread_id)
        if last == "all_clear" or (kind != "alert" and last is None) or (kind == "alert" and last):
            return False
        self._followups[thread_id] = kind
        mailbox = MailboxChannel(self.store)
        digest = hashlib.sha256(f"{draft.title}|{draft.body}".encode()).hexdigest()[:12]
        for account_id in recipients:
            key = f"{kind}:{incident_id}:{account_id}:{digest}"
            mailbox.deliver(account_id, draft, kind, key, thread_id)
        message = {
            "type": "followup",
            "thread_id": thread_id,
            "kind": kind,
            "title": draft.title,
            "body": draft.body,
        }
        peers = [p for a in recipients for p in list(self._peers.get(a, set()))]
        await asyncio.gather(*(self._safe(p, message) for p in peers))
        log.info("%s follow-up sent to %d devices", kind, len(peers))
        return True

    async def publish(self, alert: OfficialAlert) -> dict[str, Any]:
        """Store the alert (descriptions removed) and send it verbatim to every eligible device
        in one pass."""
        received = datetime.now(UTC)
        alert_id = uuid.uuid4().hex[:12]
        thread_id, closed = self.threads.assign(alert, received)
        if not closed:
            self._live[thread_id] = alert.test_only
        self.store.add_alert(alert_id, alert, received, thread_id)
        body = {
            "id": alert_id,
            "thread_id": thread_id,
            "closed": closed,
            "area": area_for(alert.text, self._segments),
            "source": alert.source,
            "kind": alert.kind,
            "status": alert.status,
            "verification": alert.verification,
            "text": alert.text,
            "official_at": alert.official_at.isoformat() if alert.official_at else None,
            "received_at": received.isoformat(),
            "link": alert.link,
        }
        targets = [
            peer
            for account_id, peers in self._peers.items()
            if not alert.test_only or self._accounts[account_id].is_test
            for peer in list(peers)
        ]
        await asyncio.gather(*(self._safe(p, {"type": "alert", "alert": body}) for p in targets))
        if closed:
            await self._close_thread(thread_id)
        log.info("%s alert sent to %d devices", alert.kind, len(targets))
        return body
