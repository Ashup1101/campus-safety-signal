"""Activity levels (quiet / elevated / high) per street segment and time window.

Built only from incidents we hold, never from anyone's movements. When the warehouse has the
city's street network, segments are generated from it (one per centerline piece) and incidents
come from gold.incident_points; otherwise the 13 hand-drawn segments match silver.incidents by
the location phrases the IU crime log uses. The hand-entered Kirkwood shootings count either way.
Sensitive offenses never count and never appear in reasons. Reasons use plain words and never name
a business; the words safe and risk are never used.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from campus_safety.geo import segments as city_segments
from campus_safety.geo.place import distance_to_lines, midpoint
from campus_safety.patterns.categories import SERIOUS, category
from campus_safety.patterns.levels import LOOKBACK_YEARS, WINDOWS
from campus_safety.patterns.levels import in_window as _in_window
from campus_safety.patterns.levels import level as _level
from campus_safety.patterns.levels import reason as _reason
from demo_server.store import Activity

SEGMENTS = Path(__file__).with_name("segments.geojson")
SAME_STRETCH_M = 25.0  # a generated piece whose middle lies this close to a hand-drawn line
DB_CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}


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


def load_segments(warehouse: Path) -> dict[str, Any]:
    """Segments generated from the city's street network, or the hand-drawn ones without it."""
    return city_segments.from_warehouse(warehouse) or load_geojson()


def is_generated(geojson: dict[str, Any]) -> bool:
    return bool(geojson.get("generated"))


def segments(geojson: dict[str, Any]) -> list[Segment]:
    return [
        Segment(
            id=f["properties"]["id"],
            name=f["properties"]["name"],
            patterns=tuple(re.compile(p) for p in f["properties"].get("match", ())),
        )
        for f in geojson["features"]
    ]


def point_incidents(db: Path) -> list[Incident]:
    """Placed real incidents (gold.incident_points) on the generated segment of their piece."""
    if not db.exists():
        return []
    with duckdb.connect(str(db), read_only=True, config=DB_CONFIG) as con:
        try:
            rows = con.execute(
                "select incident_type, severity_tier, occurred_from, street_objectid"
                " from gold.incident_points"
                " where street_objectid is not null and occurred_from is not null"
            ).fetchall()
        except duckdb.CatalogException:
            return []
    incidents = []
    for incident_type, tier, occurred, objectid in rows:
        kind = category(incident_type or "")
        serious = tier == "high" or kind in SERIOUS
        incidents.append(Incident(occurred, kind, serious, (f"street_{objectid}",)))
    return incidents


def _lines(feature: dict[str, Any]) -> tuple[tuple[tuple[float, float], ...], ...]:
    return tuple(
        tuple((float(x), float(y)) for x, y in line) for line in feature["geometry"]["coordinates"]
    )


def translate(
    incidents: Iterable[Incident], hand: dict[str, Any], generated: dict[str, Any]
) -> list[Incident]:
    """Hand-entered incidents name hand-drawn segments; move each onto the generated pieces that
    lie along the same stretch (their middle on the hand-drawn line). Unmatched ones drop out."""
    lines = {f["properties"]["id"]: _lines(f) for f in hand["features"]}
    middles = {f["properties"]["id"]: midpoint(_lines(f)) for f in generated["features"]}
    near = {
        hand_id: tuple(
            g for g, mid in middles.items() if distance_to_lines(mid, line) <= SAME_STRETCH_M
        )
        for hand_id, line in lines.items()
    }
    moved = []
    for incident in incidents:
        found = tuple(sorted({g for s in incident.segments for g in near.get(s, ())}))
        if found:
            moved.append(replace(incident, segments=found))
    return moved


def warehouse_incidents(db: Path, found: list[Segment]) -> list[Incident]:
    """Non-sensitive IU log incidents whose location names one of our segments."""
    if not db.exists():
        return []
    with duckdb.connect(str(db), read_only=True, config=DB_CONFIG) as con:
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
    by_segment: dict[str, list[Incident]] = {}
    for i in incidents:
        if start <= i.occurred_at <= now:
            for segment_id in i.segments:
                by_segment.setdefault(segment_id, []).append(i)
    rows = []
    for segment_id in segment_ids:
        mine = by_segment.get(segment_id, [])
        for window in WINDOWS:
            hits = [i for i in mine if _in_window(window, i.occurred_at, nights)]
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
