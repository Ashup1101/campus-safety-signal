"""Briefings and digests on time (local wall clock, following the demo clock):
- a briefing to every family account from 15:00 the day before an event's first night until that
  night ends;
- a daily digest per watch zone from 07:00 (the 24 hours before 07:00);
- a weekly digest per watch zone on Mondays from 07:00 (the week before).
Each message has a key and lands once (the mailbox keeps the keys). Digests hold only lower-level
reports (the alert rules send high and medium as alerts), placed no finer than a street block, and
are skipped when empty. Nothing here stores or logs message text."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, time, timedelta
from pathlib import Path

import duckdb

from campus_safety import events
from campus_safety.alerts import briefings, digests
from campus_safety.events import Event
from campus_safety.patterns.categories import category
from demo_server.mailbox import MailboxChannel
from demo_server.store import Store, Zone

log = logging.getLogger(__name__)
BRIEFING_AT, DIGEST_AT = time(15), time(7)
ALERT_TIERS = {"high", "medium"}
M_PER_DEG_LAT = 111_320.0
CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * M_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, (lat2 - lat1) * M_PER_DEG_LAT)


class Scheduler:
    def __init__(
        self,
        store: Store,
        channel: MailboxChannel,
        warehouse: Path,
        names: dict[str, str],
        calendar: Sequence[Event],
        now: Callable[[], datetime],
    ) -> None:
        self.store, self.channel, self.warehouse = store, channel, warehouse
        self.names, self.calendar, self.now = names, calendar, now

    def _family(self) -> list[str]:
        return [a.id for a in self.store.accounts() if a.role in ("student", "parent")]

    def _busy(self) -> list[briefings.Busy]:
        return [
            briefings.Busy(
                self.names.get(a.segment_id, a.segment_id), a.level, a.reason, a.incidents
            )
            for a in self.store.activity()
            if a.window == "event_night"
        ]

    def _tonight(self) -> str | None:
        rows = [a for a in self.store.activity() if a.window == "tonight"]
        busy = sum(a.level != "quiet" for a in rows)
        if not rows:
            return None
        method = "forecast model" if "forecast model" in rows[0].reason else "simple rule"
        return f"{busy} of {len(rows)} streets expected busier than usual ({method})"

    def _briefings(self, now: datetime) -> int:
        sent = 0
        for event in self.calendar:
            first, last = min(event.nights), max(event.nights)
            opens = datetime.combine(first - timedelta(days=1), BRIEFING_AT)
            closes = datetime.combine(last + timedelta(days=1), time(4))
            if not opens <= now < closes:
                continue
            draft = briefings.briefing(event, self._busy(), self._tonight())
            for account_id in self._family():
                key = f"briefing:{event.event_id}:{account_id}"
                sent += self.channel.deliver(account_id, draft, "briefing", key)
        return sent

    def _items(self, zone: Zone, start: datetime, end: datetime) -> list[digests.Item]:
        if not self.warehouse.exists():
            return []
        with duckdb.connect(str(self.warehouse), read_only=True, config=CONFIG) as con:
            try:
                rows = con.execute(
                    "select incident_type, severity_tier, occurred_from, lat, lon, street_objectid"
                    " from gold.incident_points where occurred_from >= ? and occurred_from < ?",
                    [start, end],
                ).fetchall()
            except duckdb.CatalogException:
                return []
        return [
            digests.Item(category(kind or ""), self.names.get(f"street_{objectid}"), at)
            for kind, tier, at, lat, lon, objectid in rows
            if tier not in ALERT_TIERS and _meters(zone.lat, zone.lon, lat, lon) <= zone.radius_m
        ]

    def _digests(self, now: datetime) -> int:
        if now.time() < DIGEST_AT:
            return 0
        end = datetime.combine(now.date(), DIGEST_AT)
        periods = [("daily", end - timedelta(days=1))]
        if now.weekday() == 0:
            periods.append(("weekly", end - timedelta(days=7)))
        sent = 0
        for account_id in self._family():
            for zone in self.store.zones(account_id):
                for period, start in periods:
                    key = f"digest:{period}:{end.date()}:{account_id}:{zone.name}"
                    if self.store.sent(key):
                        continue
                    draft = digests.digest(
                        period, zone.name, start, end, self._items(zone, start, end)
                    )
                    if draft:
                        sent += self.channel.deliver(account_id, draft, "digest", key)
        return sent

    def tick(self) -> int:
        """Send whatever is due now; returns how many new messages landed."""
        now = events.local(self.now())
        sent = self._briefings(now) + self._digests(now)
        if sent:
            log.info("scheduler: %d new mailbox messages", sent)
        return sent

    async def run(
        self,
        every: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        while True:
            self.tick()
            await sleep(every)
