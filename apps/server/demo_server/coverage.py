"""The console's "Data coverage" panel: which years public data covers, and where it is missing."""

from pathlib import Path
from typing import Any

import duckdb

from campus_safety import gaps


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
    found["iu_crime_log"] = [
        {"kind": kind, "start": start.isoformat(), "end": end.isoformat(), "days": days}
        for kind, start, end, days in spans
    ]
    return found
