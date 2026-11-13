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

from campus_safety.patterns.categories import SERIOUS, category
from campus_safety.patterns.levels import LOOKBACK_YEARS, WINDOWS
from campus_safety.patterns.levels import in_window as _in_window
from campus_safety.patterns.levels import level as _level
from campus_safety.patterns.levels import reason as _reason
from demo_server.store import Activity

SEGMENTS = Path(__file__).with_name("segments.geojson")


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
