"""Event nights (configs/events.yaml) and the night-time windows built on them.

A night belongs to the date it starts on: 01:30 on Nov 1 is part of the night of Oct 31. Times are
local wall-clock times in Bloomington.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CALENDAR = Path(__file__).resolve().parents[2] / "configs" / "events.yaml"
LOCAL = ZoneInfo("America/Indiana/Indianapolis")
LATE_NIGHT = (time(22), time(4))
EVENT_NIGHT = (time(18), time(4))


@dataclass(frozen=True)
class Event:
    event_id: str
    name: str
    nights: tuple[date, ...]


def load(path: Path = CALENDAR) -> list[Event]:
    events = []
    for entry in (yaml.safe_load(path.read_text()) or {}).get("events", []):
        nights = entry.get("nights")
        if not isinstance(nights, list) or not all(isinstance(n, date) for n in nights):
            raise ValueError(f"{entry.get('event_id')!r}: nights must be a list of YYYY-MM-DD")
        events.append(Event(str(entry["event_id"]), str(entry["name"]), tuple(nights)))
    return events


@cache
def event_nights(path: Path = CALENDAR) -> frozenset[date]:
    return frozenset(night for event in load(path) for night in event.nights)


def local(at: datetime) -> datetime:
    """Naive local wall time for an aware or already-local naive datetime."""
    return at.astimezone(LOCAL).replace(tzinfo=None) if at.tzinfo else at


def night_of(at: datetime) -> date:
    at = local(at)
    return at.date() - timedelta(days=1) if at.time() < time(12) else at.date()


def _between(at: datetime, window: tuple[time, time]) -> bool:
    start, end = window
    clock = local(at).time()
    return clock >= start or clock < end


def is_late_night(at: datetime) -> bool:
    return _between(at, LATE_NIGHT)


def is_event_night(at: datetime, nights: frozenset[date] | None = None) -> bool:
    nights = event_nights() if nights is None else nights
    return _between(at, EVENT_NIGHT) and night_of(at) in nights


def high_alert(at: datetime, nights: frozenset[date] | None = None) -> bool:
    """Late night or an event night: official sources are polled twice as often."""
    return is_late_night(at) or is_event_night(at, nights)
