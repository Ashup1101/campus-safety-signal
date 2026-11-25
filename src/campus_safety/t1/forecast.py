"""T1 forecast for the next nights: expected late-night calls per police zone, a level and a
plain reason. The same output whether the model or the rule made it (the scorecard says which).

A level compares the expected count with the zone's usual night over the last year: counts are
sparse (about 0.16 calls per zone-night), so quantiles would be 0 almost everywhere. A minimum
expected count keeps a very quiet zone from turning High over a fraction of a call."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from campus_safety.events import Event
from campus_safety.t1.baselines import Row
from campus_safety.t1.table import WINDOW

Predict = Callable[[Sequence[Row]], list[float]]
HORIZON = 7
ELEVATED, HIGH = 1.5, 2.5  # times the zone's usual night
MIN_ELEVATED, MIN_HIGH = 0.3, 1.0  # expected calls needed for those levels
REASONS = {
    "quiet": "About a usual night here",
    "elevated": "Expected busier than usual",
    "high": "Expected much busier than usual",
}


@dataclass(frozen=True)
class Forecast:
    zonecode: str
    night: date
    window: str
    expected: float
    level: str
    method: str
    reason: str


def level(expected: float, usual: float) -> str:
    ratio = expected / usual if usual > 0 else (float("inf") if expected > 0 else 0.0)
    if ratio >= HIGH and expected >= MIN_HIGH:
        return "high"
    if ratio >= ELEVATED and expected >= MIN_ELEVATED:
        return "elevated"
    return "quiet"


def forecast(
    table: Sequence[Row],
    start: date,
    predict: Predict,
    method: str,
    events: Sequence[Event],
    horizon: int = HORIZON,
) -> list[Forecast]:
    """`table` holds each zone's nights up to `start` - 1 (calls known)."""
    names = {night: e.name for e in events for night in e.nights}
    counts: dict[str, dict[date, int]] = {}
    for r in table:
        if r.night < start:
            counts.setdefault(r.zonecode, {})[r.night] = r.calls
    targets: list[Row] = []
    usual: dict[str, float] = {}
    for zone, by_night in sorted(counts.items()):
        last_year = [by_night.get(start - timedelta(days=d), 0) for d in range(1, 366)]
        usual[zone] = sum(last_year) / len(last_year)
        mean_4w = sum(last_year[:28]) / 28
        for k in range(horizon):
            night = start + timedelta(days=k)
            last_week = by_night.get(night - timedelta(days=7), 0)
            targets.append(
                Row(
                    zone, night, 0, night.weekday(), night.month, night in names, last_week, mean_4w
                )
            )
    found = []
    for r, expected in zip(targets, predict(targets), strict=True):
        tier = level(expected, usual[r.zonecode])
        reason = REASONS[tier]
        if tier != "quiet" and r.night in names:
            reason = f"{reason}: {names[r.night]}"
        found.append(
            Forecast(r.zonecode, r.night, WINDOW, round(expected, 3), tier, method, reason)
        )
    return found
