"""Recent placed incidents as map dots (gold.incident_points): category, day and precision only.
Never location text or names, and never sensitive offenses (the gold table holds none)."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from campus_safety.patterns.categories import category

MAX_POINTS = 1500  # newest first; a year of placed incidents is a few hundred
ATTRIBUTION = "Locations: City of Bloomington GIS street centerlines and address points"
CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}


def recent(db: Path, days: int, today: date) -> dict[str, Any]:
    rows: list[tuple[Any, ...]] = []
    if db.exists():
        with duckdb.connect(str(db), read_only=True, config=CONFIG) as con:
            try:
                rows = con.execute(
                    "select incident_type, day, precision, lat, lon from ("
                    "  select *, coalesce(cast(occurred_from as date), date_reported) as day"
                    "  from gold.incident_points"
                    ") where day between ? and ? order by day desc, lat, lon limit ?",
                    [today - timedelta(days=days), today, MAX_POINTS],
                ).fetchall()
            except duckdb.CatalogException:
                rows = []
    return {
        "type": "FeatureCollection",
        "days": days,
        "attribution": ATTRIBUTION,
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "category": category(kind or ""),
                    "day": day.isoformat(),
                    "precision": precision,
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
            for kind, day, precision, lat, lon in rows
        ],
    }
