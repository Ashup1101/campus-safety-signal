"""Quiet / elevated / high per place and time window, with a plain-words reason.

Thresholds (DECISIONS.md 2026-11-02): serious incidents weigh more than volume. Never the words
safe or risk; never a business name; sensitive offenses never counted.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from campus_safety import events
from campus_safety.patterns.categories import category, is_serious, plural

WINDOWS = {"late_night": "on late nights", "event_night": "on event nights"}
LOOKBACK_YEARS = 3
HIGH = (2, 8)  # serious, total
ELEVATED = (1, 3)


@dataclass(frozen=True)
class Observation:
    """One non-sensitive incident at a known place and time."""

    place: str  # location text or segment id
    occurred_at: datetime  # local wall time
    incident_type: str
    severity_tier: str | None = None

    @property
    def kind(self) -> str:
        return category(self.incident_type)

    @property
    def serious(self) -> bool:
        return is_serious(self.incident_type, self.severity_tier)


@dataclass(frozen=True)
class Level:
    place: str
    window: str
    level: str  # quiet | elevated | high
    reason: str
    incidents: int
    serious: int


def in_window(window: str, at: datetime, nights: frozenset[date]) -> bool:
    if window == "late_night":
        return events.is_late_night(at)
    return events.is_event_night(at, nights)


def level(serious: int, total: int) -> str:
    if serious >= HIGH[0] or total >= HIGH[1]:
        return "high"
    if serious >= ELEVATED[0] or total >= ELEVATED[1]:
        return "elevated"
    return "quiet"


def reason(window: str, kinds: Counter[str], years: set[int]) -> str:
    where = WINDOWS[window]
    if not kinds:
        return f"Nothing recorded {where} in the data we hold"
    top = [f"{n} {plural(kind, n)}" for kind, n in kinds.most_common(2)]
    span = f"in {min(years)}" if len(years) == 1 else f"{min(years)}-{max(years)}"
    joined = " and ".join(top)
    return f"{joined[0].upper()}{joined[1:]} {where} {span}"


def levels(
    observations: Iterable[Observation], now: datetime, nights: frozenset[date]
) -> list[Level]:
    """Every place that has any recent observation, in every window (quiet rows included)."""
    start = now - timedelta(days=365 * LOOKBACK_YEARS)
    recent = [o for o in observations if start <= o.occurred_at <= now]
    rows = []
    for place in sorted({o.place for o in recent}):
        for window in WINDOWS:
            hits = [
                o for o in recent if o.place == place and in_window(window, o.occurred_at, nights)
            ]
            serious = sum(o.serious for o in hits)
            kinds = Counter(o.kind for o in hits)
            years = {o.occurred_at.year for o in hits}
            rows.append(
                Level(
                    place,
                    window,
                    level(serious, len(hits)),
                    reason(window, kinds, years),
                    len(hits),
                    serious,
                )
            )
    return rows
