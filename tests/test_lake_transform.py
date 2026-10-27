"""End to end: synthetic bronze snapshots -> silver observations -> dbt -> published silver."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import boto3
import duckdb
import pytest
from crime_log_html import incident, page, section
from legacy_pdf import REPORT, make_pdf
from moto import mock_aws

from campus_safety.lake import bronze
from campus_safety.lake.cli import main
from campus_safety.lake.storage import CachedLake, FileLake, Lake, S3Lake
from campus_safety.lake.transform import TransformError, transform

DAY_1 = datetime(2026, 10, 24, 14, 17, tzinfo=UTC)
MINOR = "ILLEGAL CONSUMPTION/POSSESSION OF ALCOHOL BY MINOR"
CONTRACT = [
    "incident_id", "source", "source_ref", "source_record_id", "run_id", "ingested_at",
    "incident_type", "offense_raw", "severity_tier", "count", "date_reported", "occurred_from",
    "occurred_to", "time_precision", "location_text", "location_type", "business_name", "lat",
    "lon", "geocode_quality", "zone_id", "disposition", "is_sensitive", "injuries", "deaths",
    "weapon_involved", "summary", "confidence", "gap_id", "seed",
]  # fmt: skip


def snapshot(lake: Lake, day: int, html: str) -> None:
    bronze.write(
        lake,
        source="iu_crime_log",
        body=html.encode(),
        url="https://protect.example.edu/log.html",
        fetched_at=DAY_1 + timedelta(days=day),
        http_status=200,
        run_id=f"test-{day}",
        ext="html",
    )


def bloomington(*rows: str) -> str:
    return page(section("Bloomington", "".join(rows)))


def seed_history(lake: Lake) -> None:
    a = {"case": "900001", "offense": "BATTERY NO INJURY"}
    b = {"case": "900002", "offense": MINOR}
    c = {"case": "900003", "offense": "VEHICLE THEFT", "end": ""}
    d = {"case": "900004", "offense": "RAPE - INTERCOURSE", "location": "ALL OTHER OPEN AREAS"}
    snapshot(
        lake,
        0,
        bloomington(
            incident(**a), incident(**{**b, "offense": b["offense"] + " X2"}), incident(**c)
        ),
    )
    snapshot(
        lake,
        1,
        bloomington(
            incident(**a, disposition="SUSPECT ARRESTED"),
            incident(**{**b, "offense": b["offense"] + " X3"}),
            incident(**c),
            incident(**d),
        ),
    )
    snapshot(
        lake,
        2,
        bloomington(
            incident(**a, disposition="SUSPECT ARRESTED"),
            incident(**{**b, "offense": b["offense"] + " X3"}),
            incident(**d),
        ),
    )
    snapshot(lake, 3, "<html>redesigned</html>")


def rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    """Run test SQL with $t bound to a Parquet path under tmp_path."""
    with duckdb.connect() as con:
        return con.execute(sql.replace("$t", f"read_parquet('{path}')")).fetchall()


def test_transform_derives_state_and_history(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    seed_history(lake)
    summary = transform(lake, tmp_path / "work")
    assert (summary.snapshots, summary.parse_errors) == (4, 1)
    assert (summary.incidents, summary.cases, summary.history_rows) == (4, 4, 6)

    silver = tmp_path / "lake" / "silver"
    history = rows(
        silver / "iu_crime_log_incident_history.parquet",
        "SELECT case_number, offense_count, disposition, run_id FROM $t ORDER BY 1, observed_at",
    )
    assert history == [
        ("900001", 1, "OPEN CASE", "test-0"),
        ("900001", 1, "SUSPECT ARRESTED", "test-1"),
        ("900002", 2, "OPEN CASE", "test-0"),
        ("900002", 3, "OPEN CASE", "test-1"),
        ("900003", 1, "OPEN CASE", "test-0"),
        ("900004", 1, "OPEN CASE", "test-1"),
    ]
    current = rows(
        silver / "iu_crime_log_incidents.parquet",
        "SELECT case_number, disposition, first_seen::date, last_seen::date, sightings"
        " FROM $t ORDER BY 1",
    )
    assert current == [
        ("900001", "SUSPECT ARRESTED", DAY_1.date(), (DAY_1 + timedelta(2)).date(), 3),
        ("900002", "OPEN CASE", DAY_1.date(), (DAY_1 + timedelta(2)).date(), 3),
        ("900003", "OPEN CASE", DAY_1.date(), (DAY_1 + timedelta(1)).date(), 2),
        ("900004", "OPEN CASE", (DAY_1 + timedelta(1)).date(), (DAY_1 + timedelta(2)).date(), 2),
    ]


def test_conformed_incidents_follow_the_contract(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    seed_history(lake)
    transform(lake, tmp_path / "work")
    path = tmp_path / "lake" / "silver" / "incidents.parquet"
    assert [column[0] for column in rows(path, "DESCRIBE SELECT * FROM $t")] == CONTRACT
    found = rows(
        path,
        "SELECT source_record_id, source, count, time_precision, geocode_quality, is_sensitive"
        " FROM $t ORDER BY 1",
    )
    assert found == [
        ("900001|BATTERY NO INJURY", "official", 1, "range", "pending", False),
        (f"900002|{MINOR}", "official", 3, "range", "pending", False),
        ("900003|VEHICLE THEFT", "official", 1, "exact", "pending", False),
        ("900004|RAPE - INTERCOURSE", "official", 1, "range", "not_geocodable", True),
    ]


def test_runs_record_windows_and_redacted_parse_errors(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    seed_history(lake)
    transform(lake, tmp_path / "work")
    runs = rows(
        tmp_path / "lake" / "silver" / "iu_crime_log_runs" / "**" / "*.parquet",
        "SELECT run_id, window_end, incidents, parse_error IS NOT NULL FROM $t ORDER BY 1",
    )
    assert runs == [
        ("test-0", datetime(2026, 10, 25).date(), 3, False),
        ("test-1", datetime(2026, 10, 25).date(), 4, False),
        ("test-2", datetime(2026, 10, 25).date(), 3, False),
        ("test-3", None, 0, True),
    ]


def test_transform_is_repeatable(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    seed_history(lake)
    first = transform(lake, tmp_path / "work")
    assert transform(lake, tmp_path / "work") == first


def test_transform_needs_bronze(tmp_path: Path) -> None:
    with pytest.raises(TransformError, match="no crime log snapshots"):
        transform(FileLake(tmp_path / "lake"), tmp_path / "work")


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Lake]:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="lake-test")
        yield S3Lake("lake-test", "lake", client)


def test_transform_against_s3(s3: S3Lake, tmp_path: Path) -> None:
    seed_history(s3)
    summary = transform(CachedLake(s3, tmp_path / "cache"), tmp_path / "work")
    assert (summary.incidents, summary.history_rows) == (4, 6)
    assert "silver/incidents.parquet" in s3.keys("silver/")
    assert (tmp_path / "cache" / "bronze" / "iu_crime_log").is_dir()


def test_archive_backfill_merges_with_live_capture(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    live = bloomington(incident(case="900001", disposition="SUSPECT ARRESTED"))
    archived = bloomington(incident(case="900001"))
    snapshot(lake, 0, live)
    for run_id, body, ext, captured in (
        ("wb-1", archived.encode(), "html", datetime(2025, 3, 1, tzinfo=UTC)),
        ("wb-2", make_pdf(REPORT), "pdf", datetime(2017, 1, 5, tzinfo=UTC)),
        ("wb-3", b"<!DOCTYPE html>archive error", "pdf", datetime(2017, 1, 6, tzinfo=UTC)),
    ):
        bronze.write(
            lake,
            source="iu_crime_log_wayback",
            body=body,
            url=f"https://web.archive.org/web/{run_id}",
            fetched_at=DAY_1,
            http_status=200,
            run_id=run_id,
            ext=ext,
            captured_at=captured,
        )
    summary = transform(lake, tmp_path / "work")
    assert (summary.snapshots, summary.parse_errors, summary.incidents) == (4, 1, 3)

    silver = tmp_path / "lake" / "silver"
    history = rows(
        silver / "iu_crime_log_incident_history.parquet",
        "SELECT dataset, disposition, observed_at::date FROM $t"
        " WHERE case_number = '900001' ORDER BY observed_at",
    )
    assert history == [
        ("iu_crime_log_wayback", "OPEN CASE", date(2025, 3, 1)),
        ("iu_crime_log", "SUSPECT ARRESTED", DAY_1.date()),
    ]
    sources = rows(
        silver / "incident_sources.parquet",
        "SELECT dataset, count(*) FROM $t GROUP BY 1 ORDER BY 1",
    )
    assert sources == [("iu_crime_log", 1), ("iu_crime_log_wayback", 3)]


def test_coverage_merges_windows_and_reports_gaps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lake = FileLake(tmp_path / "lake")
    for day, window in enumerate(
        ("08/01/2026 - 08/10/2026", "08/05/2026 - 08/20/2026", "08/22/2026 - 08/30/2026")
    ):
        snapshot(lake, day, page(section("Bloomington", incident(), window=window)))
    snapshot(lake, 3, "<html>broken: covers nothing</html>")
    summary = transform(lake, tmp_path / "work")
    coverage = [row for row in summary.coverage if row[0] == "iu_crime_log"]
    assert coverage == [
        ("iu_crime_log", "covered", "2026-08-01", "2026-08-20", 20),
        ("iu_crime_log", "gap", "2026-08-21", "2026-08-21", 1),
        ("iu_crime_log", "covered", "2026-08-22", "2026-08-30", 9),
    ]
    assert [row[1:] for row in summary.coverage if row[0] == "all"] == [row[1:] for row in coverage]
    assert main(["--work-dir", str(tmp_path / "work"), "coverage"]) == 0
    assert "gap      2026-08-21 2026-08-21     1" in capsys.readouterr().out
