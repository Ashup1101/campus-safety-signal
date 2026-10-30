"""Calibration aggregates: Clery data files and BPS statistics slides. All figures are made up."""

import hashlib
import io
import json
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from legacy_pdf import make_pdf

from campus_safety import fetch
from campus_safety.bpd_cfs import pull as bpd_pull
from campus_safety.calibration import bps, cli, doe
from campus_safety.calibration.cli import years
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.lake.transform import transform

FETCHED = datetime(2026, 10, 26, tzinfo=UTC)
MANUAL_URL = "manual:manual/doe/Crime{}EXCEL.zip"
SLIDES = [
    "CALLS FOR SERVICE",
    "The department has",
    "responded to 2 calls",
    "for service through",
    "January of 2026. This is",
    "an increase of 1 calls",
    "from the same period in",
    "2025.",
    "TRAFFIC STOP COMPARISON",
    "January YTD",
    "2024 10",
    "2025 12",
    "2026 9",
    "CRIME INVOLVING WEAPONS",
    "So far in 2026, there have",
    "been 4 incidents where",
    "weapons were reportedly involved.",
    "A firearm has been",
    "reported in 3 incidents in",
    "2026 and were fired at a",
    "person in 1 of those incidents.",
]


def manifest(source: str, url: str, run_id: str = "r1") -> bronze.Manifest:
    return bronze.Manifest(source, f"bronze/{source}/x.gz", url, FETCHED, "0", 200, run_id)


def test_clery_rows_keep_iu_counts_per_year() -> None:
    header = ["UNITID_P", "INSTNM", "BRANCH", "MURD23", "BURGLA23", "BURGLA24", "FILTER24"]
    data: list[Sequence[object]] = [
        [151351001.0, "Indiana University-Bloomington", "Main Campus ", 0.0, 12.0, 9.0, 1.0],
        [999999001.0, "Elsewhere", "Main", 1.0, 2.0, 3.0, 1.0],
        [151351002.0, "Indiana University-Bloomington", "Center", "", 1.0, 0.0, 1.0],
    ]
    found = doe.clery_rows(
        manifest(doe.SOURCE, MANUAL_URL.format(2025)),
        2025,
        "oncampus",
        "crime",
        header,
        data,
    )
    assert [row[4:] for row in found] == [
        ("151351001", "Main Campus", "oncampus", "crime", "MURD", 2023, 0),
        ("151351001", "Main Campus", "oncampus", "crime", "BURGLA", 2023, 12),
        ("151351001", "Main Campus", "oncampus", "crime", "BURGLA", 2024, 9),
        ("151351002", "Center", "oncampus", "crime", "BURGLA", 2023, 1),
        ("151351002", "Center", "oncampus", "crime", "BURGLA", 2024, 0),
    ]


def test_survey_year_comes_from_the_file_name() -> None:
    assert doe.survey_year(manifest(doe.SOURCE, MANUAL_URL.format(2019))) == 2019
    with pytest.raises(ValueError, match="Crime"):
        doe.survey_year(manifest(doe.SOURCE, "https://example.org/other.zip"))


def test_packet_links_only_take_packets() -> None:
    html = (
        '<div><strong>Agenda:</strong> <a class="usa-link" href="https://bloomington.in.gov/'
        'onboard/meetingFiles/11/download"> Agenda </a></div><div><strong>Packet:</strong> '
        '<a class="usa-link" href="https://bloomington.in.gov/onboard/meetingFiles/12/download">'
        " Packet </a></div>"
    )
    assert bps.packet_links(html) == [
        ("https://bloomington.in.gov/onboard/meetingFiles/12/download", "12")
    ]


def test_bps_metrics_from_statistics_slides() -> None:
    found = bps.rows(manifest(bps.SOURCE, "https://x/12"), make_pdf(SLIDES))
    assert [row[2:] for row in found] == [
        ("calls_for_service_ytd", 2026, 1, 2026, 2),
        ("calls_for_service_change_ytd", 2026, 1, 2026, 1),
        ("traffic_stops_ytd", 2026, 1, 2024, 10),
        ("traffic_stops_ytd", 2026, 1, 2025, 12),
        ("traffic_stops_ytd", 2026, 1, 2026, 9),
        ("weapon_incidents_ytd", 2026, 1, 2026, 4),
        ("firearm_incidents_ytd", 2026, 1, 2026, 3),
        ("shots_at_person_ytd", 2026, 1, 2026, 1),
    ]


def test_packet_without_statistics_yields_nothing() -> None:
    assert bps.rows(manifest(bps.SOURCE, "https://x/13"), make_pdf(["AGENDA", "MINUTES"])) == []


def test_year_ranges() -> None:
    assert list(years("2014-2016")) == [2014, 2015, 2016]
    assert list(years("2021")) == [2021]


def test_transform_checks_feed_against_reported_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lake = FileLake(tmp_path / "lake")
    calls = [
        {"case_number": "B99-00001", "datetime": "2026-01-05T08:00:00.000", "nature": "ALARM"},
        {"case_number": "B99-00002", "datetime": "2026-01-20T08:00:00.000", "nature": "ALARM"},
        {"case_number": "B99-00003", "datetime": "2026-02-02T08:00:00.000", "nature": "ALARM"},
    ]
    for source, body, ext, run_id in (
        (bpd_pull.SOURCE, json.dumps(calls).encode(), "json", "pull-p0000"),
        (bpd_pull.METADATA_SOURCE, b'{"rowsUpdatedAt": 1767430800}', "json", "pull-meta"),
        (bps.SOURCE, make_pdf(SLIDES), "pdf", "cal-12"),
        (doe.SOURCE, b"stands in for a zip", "zip", "cal-2025"),
    ):
        bronze.write(
            lake,
            source=source,
            body=body,
            url=MANUAL_URL.format(2025) if source == doe.SOURCE else "https://x",
            fetched_at=FETCHED,
            http_status=200,
            run_id=run_id,
            ext=ext,
        )

    def fake_clery(m: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
        base = (m.key, m.sha256, m.run_id, 2025, "151351001", "Main", "oncampus", "crime", "BURGLA")
        return [(*base, 2023, 12), (*base, 2024, 9)]

    monkeypatch.setattr(doe, "rows", fake_clery)
    summary = transform(lake, tmp_path / "work")
    assert (summary.calibration_files, summary.calibration_errors) == (2, 0)
    with duckdb.connect(str(tmp_path / "work" / "warehouse.duckdb")) as con:
        check = con.execute("SELECT * FROM gold.calibration_bpd_cfs_check").fetchall()
        clery = con.execute(
            "SELECT calendar_year, count FROM silver.calibration_clery ORDER BY 1"
        ).fetchall()
    assert check == [(2026, 1, 2, 2, 0, 0.0)]
    assert clery == [(2023, 12), (2024, 9)]
    assert "silver/calibration_clery.parquet" in lake.keys("silver/")


def zip_bytes(member: str = "ReadMe.txt") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "made up")
    return buffer.getvalue()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> fetch.Page:
        raise AssertionError("import-doe must never fetch")

    monkeypatch.setattr(fetch, "polite_get", refuse)


def test_import_doe_reads_only_the_manual_folder(no_network: None, tmp_path: Path) -> None:
    folder = tmp_path / "data" / doe.MANUAL_DIR
    folder.mkdir(parents=True)
    good = zip_bytes()
    (folder / "Crime2025EXCEL.zip").write_bytes(good)
    (folder / "Crime2024EXCEL.zip").write_bytes(b"not a zip")
    (folder / "notes.txt").write_text("ignored")
    (tmp_path / "data" / "Crime2023EXCEL.zip").write_bytes(zip_bytes())  # outside manual/doe
    lake = FileLake(tmp_path / "lake")

    summary = doe.import_manual(lake, tmp_path / "data")
    assert (summary.imported, summary.present, summary.skipped) == (1, 0, 2)
    (stored,) = bronze.manifests(lake, doe.SOURCE)
    assert stored.url == "manual:manual/doe/Crime2025EXCEL.zip"
    assert stored.http_status is None
    assert stored.sha256 == hashlib.sha256(good).hexdigest()
    assert bronze.read(lake, stored) == good
    assert doe.survey_year(stored) == 2025

    again = doe.import_manual(lake, tmp_path / "data")
    assert (again.imported, again.present) == (0, 1)


def test_import_doe_cli(no_network: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "data" / doe.MANUAL_DIR
    folder.mkdir(parents=True)
    (folder / "Crime2022EXCEL.zip").write_bytes(zip_bytes())
    monkeypatch.setenv("LAKE_URI", (tmp_path / "lake").as_uri())
    assert cli.main(["--data-dir", str(tmp_path / "data"), "import-doe"]) == 0
    assert len(bronze.manifests(FileLake(tmp_path / "lake"), doe.SOURCE)) == 1


def test_import_doe_without_a_folder_imports_nothing(no_network: None, tmp_path: Path) -> None:
    summary = doe.import_manual(FileLake(tmp_path / "lake"), tmp_path / "data")
    assert (summary.imported, summary.present, summary.skipped) == (0, 0, 0)
