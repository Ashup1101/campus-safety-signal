"""BPD calls for service: pull to bronze, then transform and audit. All records are made up."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from campus_safety import fetch
from campus_safety.bpd_cfs import pull
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.lake.transform import transform


def call(
    case: str, at: str, nature: str = "TRAFFIC STOP", district: str | None = "LB101"
) -> dict[str, str]:
    record = {
        "case_number": case,
        "datetime": at,
        "nature": nature,
        "agency": "BPD",
        "report": "NO REPORT",
    }
    if district is not None:
        record["district"] = district
    return record


ALARM = call("B99-00003", "2026-01-03T09:15:00.000", nature="ALARM", district="LB2")
PAGES = [
    # B99-00002 repeats B99-00001's minute, nature, and district; ALARM appears twice.
    [
        call("B99-00001", "2026-01-01T08:00:00.000"),
        call("B99-00002", "2026-01-01T08:00:30.000"),
        ALARM,
    ],
    [ALARM, call("B99-00004", "not a time", district=None)],
]
METADATA = {"id": "t5xf-ggw6", "rowsUpdatedAt": 1767430800}  # 2026-01-03 09:00 UTC


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requested: list[str] = []

    def fake_polite_get(url: str) -> fetch.Page:
        requested.append(url)
        if url == pull.METADATA:
            body = json.dumps(METADATA)
        else:
            offset = int(url.split("%24offset=")[1].split("&")[0])
            body = json.dumps(PAGES[offset // 3] if offset < 6 else [])
        return fetch.Page(url, body.encode(), datetime.now(UTC))

    monkeypatch.setattr(fetch, "polite_get", fake_polite_get)
    return requested


def test_pull_pages_until_a_short_page(portal: list[str], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    summary = pull.pull(lake, "local-abc", page_size=3, delay=0, sleep=lambda _: None)
    assert (summary.pages, summary.rows) == (2, 5)
    assert portal[0] == pull.METADATA
    pages = bronze.manifests(lake, pull.SOURCE)
    assert [m.run_id for m in pages] == ["local-abc-p0000", "local-abc-p0001"]
    assert [m.run_id for m in bronze.manifests(lake, pull.METADATA_SOURCE)] == ["local-abc-meta"]
    assert "%24order=%3Aid" in pages[0].url


def gold(work: Path, sql: str) -> list[tuple[object, ...]]:
    with duckdb.connect(str(work / "warehouse.duckdb")) as con:
        return con.execute(sql).fetchall()


def test_transform_builds_calls_and_audit(portal: list[str], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    pull.pull(lake, "local-abc", page_size=3, delay=0, sleep=lambda _: None)
    summary = transform(lake, tmp_path / "work")
    assert (summary.snapshots, summary.bpd_pages, summary.incidents) == (0, 2, 0)

    work = tmp_path / "work"
    assert gold(work, "SELECT count(*) FROM silver.bpd_calls_for_service") == [(4,)]
    (audit,) = gold(
        work,
        "SELECT rows, case_numbers, duplicate_case_rows, unparsed_call_times, null_districts,"
        " same_minute_nature_district_rows, days_in_range, days_with_calls, missing_days,"
        " portal_refreshed_at FROM gold.bpd_cfs_audit",
    )
    assert audit == (5, 4, 1, 1, 1, 1, 3, 2, 1, datetime(2026, 1, 3, 9, 0))
    assert gold(work, "SELECT day FROM gold.bpd_cfs_missing_days") == [(date(2026, 1, 2),)]
    assert gold(work, "SELECT * FROM gold.bpd_cfs_rows_per_year") == [(2026, 4)]
    assert gold(work, "SELECT pattern, rows, districts FROM gold.bpd_cfs_district_formats") == [
        ("AA999", 2, 1),
        ("AA9", 2, 1),
        ("<AAAA>", 1, 0),
    ]
    assert gold(work, "SELECT nature, rows FROM gold.bpd_cfs_nature_counts") == [
        ("TRAFFIC STOP", 3),
        ("ALARM", 2),
    ]
    published = lake.keys("gold/")
    assert "gold/bpd_cfs_audit.parquet" in published
