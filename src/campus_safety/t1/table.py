"""T1 training table: one row per police zone and night with the late-night call count
(22:00-04:00 local; a call at 01:15 belongs to the night before) and calendar features.
Counts only: no case numbers, call types or text leave this step, and sensitive call types never
count. Zone-nights without calls are filled with 0 so the model sees quiet nights too.

The caller provides the calls as a relation named t1_calls (called_at, nature, district)."""

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import duckdb

from campus_safety.iu_crime_log.classify import is_sensitive

WINDOW = "late_night"
_LATE = """
CREATE OR REPLACE TEMP TABLE t1_late AS
SELECT
    district AS zonecode,
    CAST(CASE WHEN hour(called_at) < 4 THEN called_at - INTERVAL 1 DAY ELSE called_at END AS DATE)
        AS night
FROM t1_calls
WHERE district IS NOT NULL AND called_at IS NOT NULL
    AND (hour(called_at) >= 22 OR hour(called_at) < 4)
    AND coalesce(nature, '') NOT IN (SELECT nature FROM t1_sensitive)
"""
_TABLE = """
COPY (
    WITH counts AS (SELECT zonecode, night, count(*) AS calls FROM t1_late GROUP BY ALL),
    grid AS (
        SELECT z.zonecode, n.night
        FROM (SELECT DISTINCT zonecode FROM t1_late) AS z CROSS JOIN t1_nights AS n
    ),
    full_grid AS (
        SELECT g.zonecode, g.night, coalesce(c.calls, 0) AS calls
        FROM grid AS g LEFT JOIN counts AS c USING (zonecode, night)
    )
    SELECT
        zonecode,
        night,
        'late_night' AS "window",
        calls,
        isodow(night) - 1 AS weekday,
        month(night) AS month,
        night IN (SELECT night FROM t1_events) AS is_event,
        lag(calls, 7) OVER by_night AS last_week,
        CASE WHEN count(*) OVER last_28 = 28 THEN avg(calls) OVER last_28 END AS mean_4w
    FROM full_grid
    WINDOW
        by_night AS (PARTITION BY zonecode ORDER BY night),
        last_28 AS (PARTITION BY zonecode ORDER BY night ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING)
    ORDER BY zonecode, night
) TO $out (FORMAT parquet)
"""


def _fill(
    con: duckdb.DuckDBPyConnection, create: str, insert: str, values: Sequence[object]
) -> None:
    con.execute(create)
    if values:
        con.executemany(insert, [(v,) for v in values])


def build(con: duckdb.DuckDBPyConnection, nights: frozenset[date], out: Path) -> int:
    """Write the table for the calls in t1_calls to `out`; returns the number of rows.
    `nights` are the event nights (configs/events.yaml)."""
    natures = con.execute("SELECT DISTINCT nature FROM t1_calls WHERE nature IS NOT NULL")
    sensitive = [str(n) for (n,) in natures.fetchall() if is_sensitive(str(n))]
    _fill(
        con,
        "CREATE OR REPLACE TEMP TABLE t1_sensitive (nature VARCHAR)",
        "INSERT INTO t1_sensitive VALUES (?)",
        sensitive,
    )
    _fill(
        con,
        "CREATE OR REPLACE TEMP TABLE t1_events (night DATE)",
        "INSERT INTO t1_events VALUES (?)",
        sorted(nights),
    )
    con.execute(_LATE)
    first, last = con.execute("SELECT min(night), max(night) FROM t1_late").fetchone() or (
        None,
        None,
    )
    days = (last - first).days + 1 if first is not None and last is not None else 0
    _fill(
        con,
        "CREATE OR REPLACE TEMP TABLE t1_nights (night DATE)",
        "INSERT INTO t1_nights VALUES (?)",
        [first + timedelta(days=i) for i in range(days)],
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(_TABLE, {"out": str(out)})
    (rows,) = con.execute(
        "SELECT count(*) FROM read_parquet($out)", {"out": str(out)}
    ).fetchone() or (0,)
    return int(rows)
