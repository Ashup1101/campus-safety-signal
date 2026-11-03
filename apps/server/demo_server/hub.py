"""Connections, fan-out, and presence, all in memory.

- One fan-out: an alert goes to every connected device of every eligible account in one pass, so
  students and parents get it at the same moment. Drills and replays: test accounts only.
- Live location exists only here, only while sharing is on AND a linked parent's screen is open;
  it is dropped the moment either stops. Never stored, never logged.
- A student sees who is checking in (the label they know, e.g. "Mom") only inside the app; no
  notification, no counts, no history.
"""

import asyncio
import logging
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

from campus_safety import events
from campus_safety.official.alerts import OfficialAlert
from demo_server.store import Account, Store

SHARING = ("on", "paused", "off")
CLIENTS = ("web", "ios")

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
        elif account.role == "parent":
            message["students"] = [self._student(s) for s in self.store.students_of(account.id)]
        return message

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

    async def set_clock(self, preset: str) -> dict[str, Any]:
        self.clock.set(preset)
        state = self.clock.state()
        peers = [peer for peers in self._peers.values() for peer in peers]
        await asyncio.gather(*(self._safe(p, {"type": "clock", "clock": state}) for p in peers))
        return state

    async def publish(self, alert: OfficialAlert) -> dict[str, Any]:
        """Store the alert (descriptions removed) and send it verbatim to every eligible device
        in one pass."""
        received = datetime.now(UTC)
        alert_id = uuid.uuid4().hex[:12]
        self.store.add_alert(alert_id, alert, received)
        body = {
            "id": alert_id,
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
        log.info("%s alert sent to %d devices", alert.kind, len(targets))
        return body
