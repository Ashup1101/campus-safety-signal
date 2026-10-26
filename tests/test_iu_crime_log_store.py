import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from campus_safety.iu_crime_log import store
from campus_safety.iu_crime_log.parse import CrimeLog, Incident

DAY_1 = datetime(2026, 10, 26, 14, 17, tzinfo=UTC)
DAY_2 = DAY_1 + timedelta(days=1)
THEFT = Incident(
    case_number="900001",
    offense="THEFT FROM BUILDING LESS THAN $750",
    offense_count=1,
    date_reported=date(2026, 10, 25),
    occurred_from=datetime(2026, 10, 24, 22, 0),
    occurred_to=None,
    location="ALL OTHER CAMPUS BUILDINGS - BLOOMINGTON",
    disposition="OPEN CASE",
)


def crime_log(*incidents: Incident, end: date = date(2026, 10, 25)) -> CrimeLog:
    return CrimeLog("Bloomington", end - timedelta(days=60), end, incidents)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = store.connect(tmp_path / store.DB_NAME)
    yield connection
    connection.close()


def ingest(conn: sqlite3.Connection, log: CrimeLog, at: datetime) -> store.RunSummary:
    return store.ingest(conn, log, fetched_at=at, snapshot="raw/x.html.gz", sha256="0" * 64)


def test_first_ingest_stores_incident_with_derived_fields(conn: sqlite3.Connection) -> None:
    summary = ingest(conn, crime_log(THEFT), DAY_1)
    assert (summary.records, summary.new, summary.changed) == (1, 1, 0)
    row = conn.execute(
        "SELECT location_type, geocodable, severity, sensitive, occurred_to, first_seen"
        " FROM incidents"
    ).fetchone()
    assert row == ("catch_all", 0, "medium", 0, None, "2026-10-26T14:17:00+00:00")


def test_reingest_is_idempotent_but_moves_last_seen(conn: sqlite3.Connection) -> None:
    ingest(conn, crime_log(THEFT), DAY_1)
    summary = ingest(conn, crime_log(THEFT), DAY_2)
    assert (summary.new, summary.changed) == (0, 0)
    assert conn.execute("SELECT count(*) FROM incidents").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM incident_history").fetchone() == (1,)
    assert conn.execute("SELECT first_seen, last_seen FROM incidents").fetchone() == (
        "2026-10-26T14:17:00+00:00",
        "2026-10-27T14:17:00+00:00",
    )


def test_disposition_change_keeps_history(conn: sqlite3.Connection) -> None:
    ingest(conn, crime_log(THEFT), DAY_1)
    summary = ingest(conn, crime_log(replace(THEFT, disposition="SUSPECT ARRESTED")), DAY_2)
    assert summary.changed == 1
    assert conn.execute("SELECT disposition FROM incidents").fetchall() == [("SUSPECT ARRESTED",)]
    history = conn.execute(
        "SELECT disposition, observed_at FROM incident_history ORDER BY run_id"
    ).fetchall()
    assert history == [
        ("OPEN CASE", "2026-10-26T14:17:00+00:00"),
        ("SUSPECT ARRESTED", "2026-10-27T14:17:00+00:00"),
    ]


def test_count_change_updates_the_same_row(conn: sqlite3.Connection) -> None:
    ingest(conn, crime_log(THEFT), DAY_1)
    ingest(conn, crime_log(replace(THEFT, offense_count=3)), DAY_2)
    assert conn.execute("SELECT count(*), max(offense_count) FROM incidents").fetchone() == (1, 3)


def test_runs_record_the_page_window(conn: sqlite3.Connection) -> None:
    ingest(conn, crime_log(THEFT, end=date(2026, 10, 25)), DAY_1)
    ingest(conn, crime_log(THEFT, end=date(2026, 10, 26)), DAY_2)
    assert conn.execute("SELECT window_start, window_end FROM runs ORDER BY id").fetchall() == [
        ("2026-08-26", "2026-10-25"),
        ("2026-08-27", "2026-10-26"),
    ]


def test_snapshots_round_trip_in_time_order(tmp_path: Path) -> None:
    later = store.write_snapshot(tmp_path, b"<html>2</html>", DAY_2)
    earlier = store.write_snapshot(tmp_path, b"<html>1</html>", DAY_1)
    assert store.list_snapshots(tmp_path) == [earlier, later]
    assert store.read_snapshot(earlier) == b"<html>1</html>"
    assert store.snapshot_time(later) == DAY_2
    assert earlier.name == "20261026T141700Z.html.gz"
