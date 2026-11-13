"""Poisson-process incidents for one registered gap, with planted, labeled anomalies.

Hour-by-hour rate = yearly total / hours in a year x hour, weekday and month multipliers
(each normalized to mean 1) x event-night multiplier x any planted anomaly. Everything is
seeded, so a (gap_id, seed) pair always yields the same rows. Rows never carry a business
name, a real case number, or a sensitive offense.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from campus_safety import events
from campus_safety.gaps import Gap
from campus_safety.iu_crime_log.classify import location_type, severity
from campus_safety.synthetic.profile import Profile

EVENT_MULTIPLIER = 2.5
ANOMALIES_PER_YEAR = 2
MAX_PER_HOUR = 50  # a safety cap; real hours never reach it


@dataclass(frozen=True)
class Anomaly:
    anomaly_id: str
    zone_id: str  # location text the spike or lull is planted on
    start: datetime
    end: datetime
    multiplier: float
    kind: str  # spike | lull


@dataclass(frozen=True)
class SyntheticIncident:
    n: int
    case_number: str  # SYN-<gap_id>-<seed>-<n>: never a real case number
    occurred_at: datetime  # local wall time
    incident_type: str
    severity: str
    location: str
    location_type: str
    zone_id: str
    anomaly_id: str | None
    event_night: bool


def _normalized(weights: tuple[float, ...]) -> list[float]:
    mean = sum(weights) / len(weights)
    return [w / mean for w in weights]


def _poisson(rng: random.Random, rate: float) -> int:
    """Knuth's method; rates here are well under one per hour."""
    if rate <= 0:
        return 0
    limit, k, p = math.exp(-rate), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit or k >= MAX_PER_HOUR:
            return k
        k += 1


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def plant_anomalies(
    gap: Gap, profile: Profile, rng: random.Random, start: date, end: date
) -> list[Anomaly]:
    years = max(1, (end - start).days // 365)
    found = []
    for i in range(ANOMALIES_PER_YEAR * years):
        day = start + timedelta(days=rng.randrange(max(1, (end - start).days)))
        length = rng.choice((1, 2, 3))
        spike = rng.random() < 0.75
        found.append(
            Anomaly(
                f"{gap.gap_id}-a{i + 1}",
                _pick(rng, dict(profile.locations)),
                datetime.combine(day, time(18)),
                datetime.combine(day + timedelta(days=length), time(4)),
                round(rng.uniform(3.0, 6.0), 1) if spike else 0.2,
                "spike" if spike else "lull",
            )
        )
    return sorted(found, key=lambda a: a.start)


def generate(
    gap: Gap, profile: Profile, seed: int, nights: frozenset[date] | None = None
) -> tuple[list[SyntheticIncident], list[Anomaly]]:
    if gap.segment.start is None or gap.segment.end is None:
        raise ValueError(f"{gap.gap_id}: only gaps with a date range can be patched")
    if "all" not in gap.segment.fields:
        raise ValueError(f"{gap.gap_id}: field-level gaps (e.g. coordinates) are not patched")
    rng = random.Random(f"{gap.gap_id}|{seed}")  # noqa: S311 (simulation, not security)
    start, end = gap.segment.start, gap.segment.end
    nights = events.event_nights() if nights is None else nights
    hours, weekdays, months = (
        _normalized(profile.hours),
        _normalized(profile.weekdays),
        _normalized(profile.months),
    )
    anomalies = plant_anomalies(gap, profile, rng, start, end)
    incidents: list[SyntheticIncident] = []
    at = datetime.combine(start, time(0))
    last = datetime.combine(end, time(23))
    while at <= last:
        base = profile.total_for(at.year) / (24 * 365)
        rate = base * hours[at.hour] * weekdays[at.weekday()] * months[at.month - 1]
        on_event = events.is_event_night(at, nights)
        if on_event:
            rate *= EVENT_MULTIPLIER
        active = [a for a in anomalies if a.start <= at < a.end]
        for _ in range(_poisson(rng, rate)):
            location = _pick(rng, dict(profile.locations))
            anomaly = next((a for a in active if a.zone_id == location), None)
            if anomaly is not None and rng.random() > min(1.0, anomaly.multiplier):
                continue  # lulls drop most of their rows
            kind = _pick(rng, dict(profile.categories))
            incidents.append(
                _row(gap, seed, len(incidents), at, kind, location, anomaly, on_event, rng)
            )
        # Spikes add rows on top of the base draw, on their own zone.
        for anomaly in active:
            if anomaly.kind != "spike":
                continue
            extra = _poisson(rng, rate * (anomaly.multiplier - 1.0))
            for _ in range(extra):
                kind = _pick(rng, dict(profile.categories))
                incidents.append(
                    _row(
                        gap, seed, len(incidents), at, kind, anomaly.zone_id, anomaly, on_event, rng
                    )
                )
        at += timedelta(hours=1)
    return incidents, anomalies


def _row(
    gap: Gap,
    seed: int,
    index: int,
    at: datetime,
    kind: str,
    location: str,
    anomaly: Anomaly | None,
    on_event: bool,
    rng: random.Random,
) -> SyntheticIncident:
    minute = rng.randrange(60)
    return SyntheticIncident(
        index + 1,
        f"SYN-{gap.gap_id}-{seed}-{index + 1}",
        at.replace(minute=minute),
        kind,
        severity(kind).value,
        location,
        location_type(location).value,
        location,
        anomaly.anomaly_id if anomaly else None,
        on_event,
    )
