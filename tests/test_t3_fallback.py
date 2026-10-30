"""LLM fallback: eligibility, validation, caching, and the transform switch. Synthetic data."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from legacy_pdf import REPORT, make_pdf

from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.lake.transform import Extraction, transform
from campus_safety.t3 import fallback
from campus_safety.t3.schema import FIELDS

ODD = ["Indiana University, Bloomington", "Odd Crime Summary Format", *REPORT[3:]]
ARREST = ["Adult Arrest Log", "Agency :", "date reported: 02/16/16 report #: 1", "name: someone"]
GOOD = {
    "case_number": "900445",
    "date_reported": "2016-02-16",
    "occurred_from": "2016-02-12T17:00",
    "occurred_to": None,
    "location": "SAMPLE HALL",
    "offense": "VANDALISM, MISCHIEF",
    "offense_count": 1,
    "disposition": "OPEN CASE",
}


def manifest(ext: str) -> bronze.Manifest:
    return bronze.Manifest(
        "iu_crime_log_wayback", f"bronze/x/a.{ext}.gz", "u", datetime.now(UTC), "0", 200, "r"
    )


def test_entries_only_for_incident_pdfs() -> None:
    texts = fallback.entries(manifest("pdf"), make_pdf(ODD))
    assert texts is not None and len(texts) == 2
    assert texts[0].startswith("date reported:")
    assert fallback.entries(manifest("pdf"), make_pdf(ARREST)) is None
    assert fallback.entries(manifest("pdf"), b"<!DOCTYPE html>error") is None
    assert fallback.entries(manifest("html"), b"<html></html>") is None


@pytest.mark.parametrize(
    ("change", "ok"),
    [
        ({}, True),
        ({"date_reported": "02/16/2016"}, False),
        ({"occurred_from": "2016-02-12 17:00"}, False),
        ({"offense_count": True}, False),
        ({"offense_count": 0}, False),
        ({"case_number": ""}, False),
        ({"extra": 1}, False),
    ],
)
def test_valid(change: dict[str, object], ok: bool) -> None:
    assert fallback.valid(GOOD | change) is ok
    assert set(GOOD) == set(FIELDS)


def seed(tmp_path: Path) -> FileLake:
    lake = FileLake(tmp_path / "lake")
    for run_id, body in (("odd", make_pdf(ODD)), ("arrest", make_pdf(ARREST))):
        bronze.write(
            lake,
            source="iu_crime_log_wayback",
            body=body,
            url=f"https://web.archive.org/{run_id}",
            fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
            http_status=200,
            run_id=run_id,
            ext="pdf",
            captured_at=datetime(2016, 3, 1, tzinfo=UTC),
        )
    return lake


def test_run_asks_the_model_only_for_eligible_entries_and_caches(tmp_path: Path) -> None:
    lake = seed(tmp_path)
    calls: list[str] = []

    def chat(model: str, messages: list[dict[str, str]]) -> str:
        calls.append(messages[-1]["content"])
        return json.dumps(GOOD) if len(calls) == 1 else "I cannot help with that."

    cache = tmp_path / "cache"
    summary = fallback.run(lake, "stub", "d1", cache, chat)
    assert (summary.failed_snapshots, summary.ineligible, summary.eligible) == (2, 1, 1)
    assert (summary.entries, summary.recovered, summary.invalid) == (2, 1, 1)
    assert all("Adult Arrest" not in text for text in calls)
    again = fallback.run(lake, "stub", "d1", cache, chat)
    assert (again.cached, len(calls)) == (1, 2)


def test_transform_switch_and_verification(tmp_path: Path) -> None:
    lake = seed(tmp_path)
    cache = tmp_path / "cache"
    fallback.run(lake, "stub", "d1", cache, lambda model, messages: json.dumps(GOOD))

    def confidence(extraction: Extraction) -> list[tuple[object, ...]]:
        work = tmp_path / "work"
        transform(lake, work, extraction)
        with duckdb.connect(str(work / "warehouse.duckdb")) as con:
            return con.execute(
                "SELECT source_record_id, confidence FROM silver.incidents"
            ).fetchall()

    assert confidence(Extraction()) == []
    assert confidence(Extraction("llm_fallback", cache)) == [("900445|VANDALISM, MISCHIEF", 0.5)]
    verified = frozenset({("900445", "VANDALISM, MISCHIEF")})
    assert confidence(Extraction("llm_fallback", cache, verified)) == [
        ("900445|VANDALISM, MISCHIEF", 0.9)
    ]
