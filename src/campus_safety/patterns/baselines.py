"""Nightly baselines, anomaly detection and short forecasts per place.

A night runs 18:00 to 04:00 and belongs to the date it starts on (events.night_of). The
expected count for a night is the mean of the same weekday's nights over the previous
BASELINE_WEEKS, times a learned event-night multiplier when the night is an event night. An
anomaly is a night whose observed count is unlikely under Poisson(expected). No scipy: the
Poisson tail is summed directly, which is exact for the small counts seen here.
"""

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from campus_safety import events
from campus_safety.patterns.levels import Observation

BASELINE_WEEKS = 8
MIN_OBSERVED = 3  # a night with fewer incidents is never an anomaly, whatever the baseline
ALPHA = 0.01
FLOOR = 0.25  # expected count floor: a quiet place still gets a baseline
NIGHT = (time(18), time(4))


@dataclass(frozen=True)
class Anomaly:
    place: str
    night: date
    observed: int
    expected: float
    p_value: float
    event_night: bool


@dataclass(frozen=True)
class Forecast:
    place: str
    night: date
    expected: float
    event_night: bool


@dataclass(frozen=True)
class Baseline:
    place: str
    weekday: int  # 0 = Monday
    mean_per_night: float


def is_night(at: datetime) -> bool:
    clock = events.local(at).time()
    return clock >= NIGHT[0] or clock < NIGHT[1]


def nightly_counts(observations: Iterable[Observation]) -> dict[tuple[str, date], int]:
    counts: Counter[tuple[str, date]] = Counter()
    for o in observations:
        if is_night(o.occurred_at):
            counts[o.place, events.night_of(o.occurred_at)] += 1
    return dict(counts)


def poisson_tail(k: int, rate: float) -> float:
    """P(X >= k) for X ~ Poisson(rate)."""
    if k <= 0:
        return 1.0
    if rate <= 0:
        return 0.0
    term = math.exp(-rate)
    below = term
    for i in range(1, k):
        term *= rate / i
        below += term
    return max(0.0, min(1.0, 1.0 - below))


def event_multiplier(
    counts: dict[tuple[str, date], int], nights: frozenset[date], start: date, end: date
) -> float:
    """Mean event-night count over mean normal-night count, per place-night, floored at 1."""
    places = {place for place, _ in counts}
    if not places:
        return 1.0
    span = [start + timedelta(days=d) for d in range((end - start).days + 1)]
    event = [n for n in span if n in nights]
    normal = [n for n in span if n not in nights]
    if not event or not normal:
        return 1.0
    per_event = sum(counts.get((p, n), 0) for p in places for n in event) / (
        len(event) * len(places)
    )
    per_normal = sum(counts.get((p, n), 0) for p in places for n in normal) / (
        len(normal) * len(places)
    )
    return max(1.0, per_event / per_normal) if per_normal > 0 else 1.0


def expected(
    place: str,
    night: date,
    counts: dict[tuple[str, date], int],
    nights: frozenset[date],
    multiplier: float,
) -> float:
    same_weekday = [night - timedelta(weeks=w) for w in range(1, BASELINE_WEEKS + 1)]
    normal = [n for n in same_weekday if n not in nights]
    base = sum(counts.get((place, n), 0) for n in normal) / len(normal) if normal else 0.0
    base = max(base, FLOOR)
    return base * multiplier if night in nights else base


def detect(
    observations: Iterable[Observation],
    nights: frozenset[date],
    as_of: datetime,
    since: date | None = None,
    alpha: float = ALPHA,
) -> list[Anomaly]:
    counts = nightly_counts(observations)
    if not counts:
        return []
    last = events.night_of(as_of)
    first = since or (last - timedelta(weeks=BASELINE_WEEKS * 2))
    multiplier = event_multiplier(counts, nights, min(n for _, n in counts), last)
    found = []
    for (place, night), observed in sorted(counts.items()):
        if not first <= night <= last or observed < MIN_OBSERVED:
            continue
        rate = expected(place, night, counts, nights, multiplier)
        p = poisson_tail(observed, rate)
        if p < alpha:
            found.append(Anomaly(place, night, observed, round(rate, 3), p, night in nights))
    return found


def forecast(
    observations: Iterable[Observation], nights: frozenset[date], as_of: datetime, days: int = 7
) -> list[Forecast]:
    counts = nightly_counts(observations)
    if not counts:
        return []
    tonight = events.night_of(as_of)
    multiplier = event_multiplier(counts, nights, min(n for _, n in counts), tonight)
    recent = {p for p, n in counts if n >= tonight - timedelta(weeks=BASELINE_WEEKS)}
    return [
        Forecast(
            place,
            night,
            round(expected(place, night, counts, nights, multiplier), 3),
            night in nights,
        )
        for place in sorted(recent)
        for night in (tonight + timedelta(days=d) for d in range(1, days + 1))
    ]


def baselines(observations: Iterable[Observation], as_of: datetime) -> list[Baseline]:
    counts = nightly_counts(observations)
    tonight = events.night_of(as_of)
    span = [tonight - timedelta(days=d) for d in range(1, BASELINE_WEEKS * 7 + 1)]
    rows = []
    for place in sorted({p for p, _ in counts}):
        for weekday in range(7):
            same = [n for n in span if n.weekday() == weekday]
            mean = sum(counts.get((place, n), 0) for n in same) / len(same) if same else 0.0
            rows.append(Baseline(place, weekday, round(mean, 3)))
    return rows


@dataclass(frozen=True)
class Score:
    planted: int
    detected: int
    hits: int  # planted spikes with at least one detected night inside their window
    false_alarms: int  # detected nights outside every planted spike

    @property
    def precision(self) -> float:
        return (self.detected - self.false_alarms) / self.detected if self.detected else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.planted if self.planted else 0.0


def score(detected: list[Anomaly], planted: list[tuple[str, datetime, datetime]]) -> Score:
    """planted: (place, start, end) spike windows. A detected night matches a spike when its
    place is the spike's and the night starts inside the window."""

    def inside(anomaly: Anomaly, spike: tuple[str, datetime, datetime]) -> bool:
        place, start, end = spike
        at = datetime.combine(anomaly.night, time(18))
        return anomaly.place == place and start <= at < end

    hits = sum(any(inside(a, s) for a in detected) for s in planted)
    false_alarms = sum(not any(inside(a, s) for s in planted) for a in detected)
    return Score(len(planted), len(detected), hits, false_alarms)
