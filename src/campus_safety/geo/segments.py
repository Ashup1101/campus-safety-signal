"""Activity segments generated from the city's road centerlines for campus and downtown: one per
centerline piece (about a block), named like "E Kirkwood Ave, 400 block (Grant to Dunn)".
Access drives (often named after a business), trails and unnumbered pieces are left out, and a
cross street that is an access drive is never named."""

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import duckdb

from campus_safety.geo.normalize import DIRECTIONS, SUFFIXES

ATTRIBUTION = "Street geometry: City of Bloomington GIS road centerlines"
NOTE = "Generated from the city's road centerlines for campus and downtown (one per piece)."
LEFT_OUT = re.compile(r"ACCESS DRIVE|\bTRAIL\b|TURNAROUND", re.IGNORECASE)


def _title(name: str) -> str:
    """'E 10th ST' -> 'E 10th St'."""
    words = name.split()
    if len(words) > 1 and words[-1].upper() in SUFFIXES:
        words[-1] = words[-1].capitalize()
    return " ".join(words)


def _short(name: str | None) -> str:
    """'N Eagleson Ave' -> 'Eagleson'; access drives and dead ends in plain words."""
    upper = (name or "").upper()
    if "ACCESS DRIVE" in upper:
        return "an access drive"
    if upper.strip() == "DEAD END" or not upper.strip():
        return "dead end"
    words = (name or "").split()
    if len(words) > 1 and words[0].upper() in DIRECTIONS:
        words = words[1:]
    if len(words) > 1 and words[-1].upper() in SUFFIXES:
        words = words[:-1]
    return " ".join(words)


def _blocks(low: int | None, high: int | None) -> str | None:
    if not low and not high:
        return None
    first, last = (low or high or 0) // 100 * 100, (high or low or 0) // 100 * 100
    return f"{first} block" if first == last else f"{first} to {last} blocks"


def _multiline(geometry: str) -> dict[str, Any]:
    shape = json.loads(geometry)
    lines = [shape["coordinates"]] if shape["type"] == "LineString" else shape["coordinates"]
    return {
        "type": "MultiLineString",
        "coordinates": [[[round(x, 6), round(y, 6)] for x, y, *_ in line] for line in lines],
    }


def feature(row: Mapping[str, Any]) -> dict[str, Any] | None:
    name = str(row["fullname"] or "")
    blocks = _blocks(row["lowadd"], row["highadd"])
    if not name or LEFT_OUT.search(name) or blocks is None:
        return None
    segment_id = f"street_{int(row['objectid'])}"
    label = f"{_title(name)}, {blocks} ({_short(row['lowxst'])} to {_short(row['highxst'])})"
    return {
        "type": "Feature",
        "id": segment_id,
        "properties": {
            "id": segment_id,
            "name": label,
            "street_objectid": int(row["objectid"]),
        },
        "geometry": _multiline(str(row["geometry"])),
    }


def generate(streets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    found = (feature(r) for r in sorted(streets, key=lambda r: int(r["objectid"])))
    return {
        "type": "FeatureCollection",
        "attribution": ATTRIBUTION,
        "note": NOTE,
        "features": [f for f in found if f is not None],
    }


def from_warehouse(db: Path) -> dict[str, Any] | None:
    """Segments from silver.geo_streets, or None when the warehouse has no street network."""
    if not db.exists():
        return None
    config: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
    with duckdb.connect(str(db), read_only=True, config=config) as con:
        try:
            cursor = con.execute(
                "SELECT objectid, fullname, lowadd, highadd, lowxst, highxst, geometry"
                " FROM silver.geo_streets"
            )
        except duckdb.CatalogException:
            return None
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]
    found = generate(rows)
    return found if found["features"] else None
