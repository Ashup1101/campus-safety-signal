"""Activity levels (quiet / elevated / high) per street segment and time window.

Built only from incidents we hold, never from anyone's movements: silver.incidents matched to
segments by the location phrases the IU crime log uses, plus the hand-entered Kirkwood shootings.
Sensitive offenses never count and never appear in reasons. Reasons use plain words and never name
a business; the words safe and risk are never used.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from campus_safety import events
from demo_server.store import Activity

SEGMENTS = Path(__file__).with_name("segments.geojson")
WINDOWS = {"late_night": "on late nights", "event_night": "on event nights"}
LOOKBACK_YEARS = 3
# Demo thresholds (DECISIONS.md 2026-11-02): serious incidents weigh more than volume.
HIGH = (2, 8)  # serious, total
ELEVATED = (1, 3)

_CATEGORIES = [
    ("shooting", r"SHOOTING|SHOTS FIRED|DISCHARG"),
    ("robbery", r"ROBBERY"),
    ("weapons incident", r"WEAPON|FIREARM|HANDGUN|\bGUN\b"),
    ("assault", r"ASSAULT|BATTERY"),
    ("burglary", r"BURGLARY|UNLAWFUL ENTRY"),
    ("traffic incident", r"DRIVING|CRASH|HIT & RUN|OPERATING|LICENSE"),
    ("theft", r"THEFT|LARCENY|SHOPLIFT"),
    ("vandalism report", r"VANDAL|MISCHIEF|GRAFFITI"),
    ("alcohol incident", r"ALCOHOL|LIQUOR|INTOXICAT|DRUNK|CONSUMPTION"),
    ("drug incident", r"DRUG|NARCOTIC|MARIJUANA|PARAPHERNALIA|METHAMPHETAMINE|COCAINE"),
    ("harassment report", r"HARASSMENT|INTIMIDATION"),
    ("disorderly conduct report", r"DISORDERLY|DISTURB"),
    ("trespass report", r"TRESPASS"),
    ("fake ID case", r"FALSE .*IDENTIFICATION|FAKE ID"),
    ("police obstruction report", r"RESISTING|OBSTRUCTION"),
]
SERIOUS = {"shooting", "robbery", "weapons incident"}


@dataclass(frozen=True)
class Segment:
    id: str
    name: str
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, location: str) -> bool:
        text = location.upper()
        return any(p.search(text) for p in self.patterns)


@dataclass(frozen=True)
class Incident:
    occurred_at: datetime  # local wall time
    category: str  # singular plain noun
    serious: bool
    segments: tuple[str, ...]


def load_geojson(path: Path = SEGMENTS) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def segments(geojson: dict[str, Any]) -> list[Segment]:
    return [
        Segment(
            id=f["properties"]["id"],
            name=f["properties"]["name"],
            patterns=tuple(re.compile(p) for p in f["properties"]["match"]),
        )
        for f in geojson["features"]
    ]


def category(incident_type: str) -> str:
    text = incident_type.upper()
    return next((name for name, rx in _CATEGORIES if re.search(rx, text)), "other incident")


def plural(noun: str, n: int) -> str:
    if n == 1:
        return noun
    return noun[:-1] + "ies" if noun.endswith("y") and noun[-2] not in "aeiou" else noun + "s"


def warehouse_incidents(db: Path, found: list[Segment]) -> list[Incident]:
    """Non-sensitive IU log incidents whose location names one of our segments."""
    if not db.exists():
        return []
    config: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
    with duckdb.connect(str(db), read_only=True, config=config) as con:
        rows = con.execute(
            "select location_text, incident_type, severity_tier, occurred_from"
            " from silver.incidents where not is_sensitive and occurred_from is not null"
            " and location_text is not null"
        ).fetchall()
    incidents = []
    for location, incident_type, tier, occurred in rows:
        ids = tuple(s.id for s in found if s.matches(location))
        if ids:
            kind = category(incident_type or "")
            serious = tier == "high" or kind in SERIOUS
            incidents.append(Incident(occurred, kind, serious, ids))
    return incidents


def manual_incidents(path: Path) -> list[Incident]:
    if not path.exists():
        return []
    entries = (yaml.safe_load(path.read_text()) or {}).get("incidents", [])
    return [
        Incident(
            occurred_at=e["occurred_at"],
            category=str(e["category"]),
            serious=str(e["category"]) in SERIOUS,
            segments=tuple(e["segments"]),
        )
        for e in entries
    ]


def _in_window(window: str, at: datetime, nights: frozenset[date]) -> bool:
    if window == "late_night":
        return events.is_late_night(at)
    return events.is_event_night(at, nights)


def _reason(window: str, kinds: Counter[str], years: set[int]) -> str:
    where = WINDOWS[window]
    if not kinds:
        return f"Nothing recorded {where} in the data we hold"
    top = [f"{n} {plural(kind, n)}" for kind, n in kinds.most_common(2)]
    span = f"in {min(years)}" if len(years) == 1 else f"{min(years)}-{max(years)}"
    joined = " and ".join(top)
    return f"{joined[0].upper()}{joined[1:]} {where} {span}"


def _level(serious: int, total: int) -> str:
    if serious >= HIGH[0] or total >= HIGH[1]:
        return "high"
    if serious >= ELEVATED[0] or total >= ELEVATED[1]:
        return "elevated"
    return "quiet"


def levels(
    segment_ids: Iterable[str],
    incidents: Iterable[Incident],
    now: datetime,
    nights: frozenset[date],
) -> list[Activity]:
    start = now - timedelta(days=365 * LOOKBACK_YEARS)
    recent = [i for i in incidents if start <= i.occurred_at <= now]
    rows = []
    for segment_id in segment_ids:
        for window in WINDOWS:
            hits = [
                i
                for i in recent
                if segment_id in i.segments and _in_window(window, i.occurred_at, nights)
            ]
            serious = sum(i.serious for i in hits)
            kinds = Counter(i.category for i in hits)
            years = {i.occurred_at.year for i in hits}
            rows.append(
                Activity(
                    segment_id=segment_id,
                    window=window,
                    level=_level(serious, len(hits)),
                    reason=_reason(window, kinds, years),
                    incidents=len(hits),
                    serious=serious,
                )
            )
    return rows
