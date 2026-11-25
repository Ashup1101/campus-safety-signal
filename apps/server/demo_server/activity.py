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
from demo_server.area import street_core
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


Point = tuple[float, float]
METHOD_WORDS = {"model": "forecast model", "rule": "simple rule"}


def _polygons(shape: dict[str, Any]) -> list[list[list[Point]]]:
    raw = [shape["coordinates"]] if shape["type"] == "Polygon" else shape["coordinates"]
    return [[[(float(x), float(y)) for x, y, *_ in ring] for ring in polygon] for polygon in raw]


def _in_ring(point: Point, ring: list[Point]) -> bool:
    x, y, inside = point[0], point[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _inside(point: Point, polygons: list[list[list[Point]]]) -> bool:
    return any(
        _in_ring(point, polygon[0]) and not any(_in_ring(point, hole) for hole in polygon[1:])
        for polygon in polygons
    )


def tonight_rows(db: Path, geojson: dict[str, Any], night: date) -> list[Activity]:
    """Tonight's level for each generated segment from gold.tonight, through the police zone its
    middle lies in. No forecast for the night (or no zone) means no tonight row: never invented."""
    if not db.exists():
        return []
    with duckdb.connect(str(db), read_only=True, config=DB_CONFIG) as con:
        try:
            forecast = con.execute(
                "select zonecode, level, reason, method from gold.tonight"
                " where night = ? and \"window\" = 'late_night'",
                [night],
            ).fetchall()
            zones = con.execute("select zonecode, geometry from silver.geo_law_zones").fetchall()
        except duckdb.CatalogException:
            return []
    by_zone = {zone: (level, reason, method) for zone, level, reason, method in forecast}
    shapes = []
    for zone, geometry in zones:
        if zone in by_zone and geometry:
            polygons = _polygons(json.loads(geometry))
            xs = [x for polygon in polygons for x, _ in polygon[0]]
            ys = [y for polygon in polygons for _, y in polygon[0]]
            shapes.append((zone, (min(xs), min(ys), max(xs), max(ys)), polygons))
    rows = []
    for feature in geojson["features"]:
        x, y = midpoint(_lines(feature))
        zone = next(
            (
                z
                for z, (x0, y0, x1, y1), polygons in shapes
                if x0 <= x <= x1 and y0 <= y <= y1 and _inside((x, y), polygons)
            ),
            None,
        )
        if zone:
            level, reason, method = by_zone[zone]
            words = f"{reason} (city calls for service, {METHOD_WORDS.get(method, method)})"
            rows.append(Activity(feature["properties"]["id"], "tonight", level, words, 0, 0))
    return rows


def translate(
    incidents: Iterable[Incident], hand: dict[str, Any], generated: dict[str, Any]
) -> list[Incident]:
    """Hand-entered incidents name hand-drawn segments; move each onto the generated piece of the
    same street that lies along it (its middle on the hand-drawn line). A hand-drawn stretch that
    covers several pieces says nothing about which one, so it drops out rather than counting on
    every piece; so does one with no matching piece."""
    lines = {
        f["properties"]["id"]: (_lines(f), street_core(f["properties"]["name"]))
        for f in hand["features"]
    }
    pieces = [
        (f["properties"]["id"], midpoint(_lines(f)), street_core(f["properties"]["name"]))
        for f in generated["features"]
    ]
    near: dict[str, tuple[str, ...]] = {}
    for hand_id, (line, street) in lines.items():
        found = [
            g
            for g, mid, core in pieces
            if core == street and distance_to_lines(mid, line) <= SAME_STRETCH_M
        ]
        near[hand_id] = tuple(found) if len(found) == 1 else ()
    moved = []
    for incident in incidents:
        ids = tuple(sorted({g for s in incident.segments for g in near.get(s, ())}))
        if ids:
            moved.append(replace(incident, segments=ids))
    return moved


def warehouse_incidents(db: Path, found: list[Segment]) -> list[Incident]:
    """Non-sensitive IU log incidents whose location names one of our segments."""
    if not db.exists():
        return []
    with duckdb.connect(str(db), read_only=True, config=DB_CONFIG) as con:
        try:
            rows = con.execute(
                "select location_text, incident_type, severity_tier, occurred_from"
                " from silver.incidents where not is_sensitive and occurred_from is not null"
                " and location_text is not null"
            ).fetchall()
        except duckdb.CatalogException:  # a partial warehouse: no incidents to count
            return []
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
