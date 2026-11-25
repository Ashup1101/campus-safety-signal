"""The console's Data coverage panel: how many incidents are placed, per kind. Made-up rows."""

from pathlib import Path

import duckdb

from demo_server.coverage import coverage
from demo_server.seed import Settings


def test_coverage_counts_placed_incidents_per_location_kind(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE SCHEMA silver; CREATE SCHEMA gold")
        con.execute(
            "CREATE TABLE gold.iu_crime_log_coverage (dataset VARCHAR, kind VARCHAR,"
            " range_start DATE, range_end DATE, days INT)"
        )
        con.execute("CREATE TABLE gold.bpd_cfs_rows_per_year (year INT, rows BIGINT)")
        con.execute(
            "CREATE TABLE silver.incidents (source VARCHAR, is_sensitive BOOLEAN,"
            " location_type VARCHAR, lat DOUBLE)"
        )
        con.execute(
            "INSERT INTO silver.incidents VALUES ('official', false, 'street_segment', 39.1),"
            " ('official', false, 'street_segment', null), ('official', false, 'place', null),"
            " ('official', true, 'address', null), ('synthetic', false, 'block', 39.1)"
        )
    found = coverage(db, Settings().gaps)
    # Sensitive and synthetic rows are never counted.
    assert found["geocoding"] == [
        {"kind": "street_segment", "incidents": 2, "placed": 1},
        {"kind": "place", "incidents": 1, "placed": 0},
    ]


def test_coverage_still_shows_without_silver_incidents(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE SCHEMA gold")
        con.execute(
            "CREATE TABLE gold.iu_crime_log_coverage (dataset VARCHAR, kind VARCHAR,"
            " range_start DATE, range_end DATE, days INT)"
        )
        con.execute("CREATE TABLE gold.bpd_cfs_rows_per_year (year INT, rows BIGINT)")
        con.execute("INSERT INTO gold.bpd_cfs_rows_per_year VALUES (2025, 10)")
    found = coverage(db, Settings().gaps)
    assert (found["geocoding"], found["bpd_calls_per_year"]) == ([], [{"year": 2025, "calls": 10}])
