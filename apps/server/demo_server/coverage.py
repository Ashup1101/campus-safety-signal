"""The console's "Data coverage" panel: which years public data covers, where it is missing, and
how many real incidents are placed on the map per kind of location (sensitive ones never count)."""

from pathlib import Path
from typing import Any

import duckdb

from campus_safety import gaps

# Shown in this order; buildings wait on a public source (gate 8), general areas are never mapped.
KINDS = ("street_segment", "address", "block", "place", "catch_all")


def coverage(warehouse: Path, register: Path) -> dict[str, Any]:
    found: dict[str, Any] = {
        "gaps": [
            {
                "gap_id": gap.gap_id,
                "source": gap.segment.source,
                "start": gap.segment.start.isoformat() if gap.segment.start else None,
                "end": gap.segment.end.isoformat() if gap.segment.end else None,
                "fields": list(gap.segment.fields),
                "reason": gap.reason,
            }
            for gap in gaps.load(register)
        ],
        "iu_crime_log": [],
        "bpd_calls_per_year": [],
        "geocoding": [],
    }
    if not warehouse.exists():
        return found
    config: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
    with duckdb.connect(str(warehouse), read_only=True, config=config) as con:
        spans = con.execute(
            "select kind, range_start, range_end, days from gold.iu_crime_log_coverage"
            " where dataset = 'all' order by range_start"
        ).fetchall()
        years = con.execute("select year, rows from gold.bpd_cfs_rows_per_year order by year")
        found["bpd_calls_per_year"] = [{"year": y, "calls": n} for y, n in years.fetchall()]
        placed = con.execute(
            "select location_type, count(*), count(lat) from silver.incidents"
            " where source = 'official' and not is_sensitive group by 1"
        ).fetchall()
    by_kind = {kind: (total, on_map) for kind, total, on_map in placed}
    found["geocoding"] = [
        {"kind": kind, "incidents": by_kind[kind][0], "placed": by_kind[kind][1]}
        for kind in KINDS
        if kind in by_kind
    ]
    found["iu_crime_log"] = [
        {"kind": kind, "start": start.isoformat(), "end": end.isoformat(), "days": days}
        for kind, start, end, days in spans
    ]
    return found
