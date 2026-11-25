"""T1 training table: zone x night counts with calendar features. Made-up calls."""

from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from campus_safety.t1 import table

COLUMNS = [
    "zonecode", "night", "window", "calls", "weekday", "month", "is_event", "last_week", "mean_4w",
]  # fmt: skip


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t1_calls (case_number VARCHAR, called_at TIMESTAMP, nature VARCHAR,"
        " district VARCHAR, report VARCHAR)"
    )
    rows = [
        ("c1", datetime(2026, 3, 1, 22, 30), "NOISE COMPLAINT", "LB101", "r"),
        (
            "c2",
            datetime(2026, 3, 2, 1, 15),
            "THEFT",
            "LB101",
            "r",
        ),  # after midnight: night of Mar 1
        ("c3", datetime(2026, 3, 2, 12, 0), "THEFT", "LB101", "r"),  # afternoon: not late night
        ("c4", datetime(2026, 3, 1, 23, 0), "SEXUAL ASSAULT", "LB101", "r"),  # sensitive: dropped
        ("c5", datetime(2026, 3, 8, 3, 30), "THEFT", "LB102", "r"),  # DST night: night of Mar 7
        ("c6", datetime(2026, 3, 8, 22, 0), "THEFT", "LB101", "r"),
    ]
    con.executemany("INSERT INTO t1_calls VALUES (?, ?, ?, ?, ?)", rows)
    return con


def test_counts_per_zone_and_night_with_zero_nights_filled(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    out = tmp_path / "train.parquet"
    rows = table.build(con, frozenset({date(2026, 3, 7)}), out)
    found = duckdb.execute("SELECT * FROM read_parquet(?) ORDER BY zonecode, night", [str(out)])
    assert [c[0] for c in found.description] == COLUMNS
    data = {(z, n): rest for z, n, *rest in found.fetchall()}
    assert rows == len(data) == 2 * 8  # 2 zones x nights Mar 1..Mar 8
    assert data[("LB101", date(2026, 3, 1))][1] == 2  # c1 + c2; c3 afternoon, c4 sensitive
    assert data[("LB102", date(2026, 3, 1))][1] == 0
    assert data[("LB102", date(2026, 3, 7))][1:] == [1, 5, 3, True, None, None]  # Sat, March
    assert data[("LB101", date(2026, 3, 8))][1:4] == [1, 6, 3]
    assert data[("LB101", date(2026, 3, 8))][5] == 2  # last week = Mar 1


def test_rolling_features_use_only_earlier_nights(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    start = datetime(2026, 1, 1, 23, 0)
    con.executemany(
        "INSERT INTO t1_calls VALUES (?, ?, 'THEFT', 'LB103', 'r')",
        [(f"r{i}", start + timedelta(days=i)) for i in range(40)],
    )
    out = tmp_path / "t.parquet"
    table.build(con, frozenset(), out)
    rows = duckdb.execute(
        "SELECT night, calls, mean_4w FROM read_parquet(?) WHERE zonecode = 'LB103' ORDER BY night",
        [str(out)],
    ).fetchall()
    assert rows[27][2] is None  # fewer than 28 earlier nights
    assert rows[28][2] == pytest.approx(1.0)  # 28 earlier nights, one call each
