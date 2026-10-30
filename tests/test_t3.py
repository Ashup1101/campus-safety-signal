"""T3-lite dataset and scoring. All incidents are synthetic."""

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from crime_log_html import incident, page, section
from legacy_pdf import REPORT, make_pdf

from campus_safety.iu_crime_log.parse import parse_crime_log
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.t3 import pairs
from campus_safety.t3.privacy import PersonScreen
from campus_safety.t3.schema import FIELDS, messages, target
from campus_safety.t3.score import parse_output, score

ROW = incident(case="900001", offense="ILLEGAL CONSUMPTION/POSSESSION OF ALCOHOL BY MINOR X3")


def test_target_matches_the_parsed_incident() -> None:
    (only,) = parse_crime_log(page(section("Bloomington", ROW))).incidents
    assert target(only) == {
        "case_number": "900001",
        "date_reported": "2026-10-25",
        "occurred_from": "2026-10-24T22:00",
        "occurred_to": "2026-10-24T23:30",
        "location": "SAMPLE HALL",
        "offense": "ILLEGAL CONSUMPTION/POSSESSION OF ALCOHOL BY MINOR",
        "offense_count": 3,
        "disposition": "OPEN CASE",
    }
    assert list(target(only)) == list(FIELDS)


def test_messages_carry_the_answer_only_for_training() -> None:
    assert [m["role"] for m in messages("<tr>...</tr>")] == ["system", "user"]
    chat = messages("<tr>...</tr>", {"case_number": "1"})
    assert chat[-1] == {"role": "assistant", "content": '{"case_number": "1"}'}


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ('{"case_number": "1"}', {"case_number": "1"}),
        ('```json\n{"case_number": "1"}\n```', {"case_number": "1"}),
        ("the case number is 1", None),
        ("[1, 2]", None),
    ],
)
def test_parse_output(text: str, parsed: dict[str, str] | None) -> None:
    assert parse_output(text) == parsed


def test_score_counts_fields_and_invalid_json() -> None:
    expected = [dict.fromkeys(FIELDS, "x") | {"offense_count": 1} for _ in range(3)]
    right = json.dumps(expected[0])
    wrong_location = json.dumps(expected[1] | {"location": "elsewhere"})
    report = score([right, wrong_location, "not json"], expected)
    summary = report.summary()
    assert summary["valid_json_rate"] == pytest.approx(2 / 3)
    assert summary["exact_case_number"] == pytest.approx(2 / 3)
    assert summary["exact_location"] == pytest.approx(1 / 3)
    assert summary["exact_all_fields"] == pytest.approx(1 / 3)
    assert report.errors["location"] == [1, 2]


def write(lake: FileLake, html_or_pdf: bytes, ext: str, at: datetime, run_id: str) -> None:
    bronze.write(
        lake,
        source="iu_crime_log" if ext == "html" else "iu_crime_log_wayback",
        body=html_or_pdf,
        url="https://example.org/log",
        fetched_at=at,
        http_status=200,
        run_id=run_id,
        ext=ext,
    )


def html_day(day: date, *cases: str) -> bytes:
    stamp = day.strftime("%m/%d/%Y")
    rows = "".join(incident(case=c, reported=stamp) for c in cases)
    return page(section("Bloomington", rows)).encode()


def test_collect_dedupes_and_screens_people(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    at = datetime(2026, 10, 26, tzinfo=UTC)
    write(lake, html_day(date(2026, 10, 25), "900001", "900002"), "html", at, "r1")
    write(lake, html_day(date(2026, 10, 25), "900001"), "html", at + timedelta(days=1), "r2")
    write(lake, make_pdf(REPORT), "pdf", at, "r3")
    write(lake, b"<html>arrest log, never parsed</html>", "html", at, "r4")

    found, counts = pairs.collect(lake, has_person=lambda text: "900002" in text)
    assert counts["snapshots_unparsed"] == 1
    assert counts["duplicates"] == 1
    assert counts["dropped_person"] == 1
    assert sorted(p.layout for p in found) == ["html", "pdf_report", "pdf_report"]


def test_time_based_splits(tmp_path: Path) -> None:
    def pair(day: str, layout: str, n: int) -> pairs.Pair:
        return pairs.Pair(f"{day}{layout}{n}", "d", "ref", layout, day, "src", {})

    rows = (
        [pair("2016-03-01", "pdf_report", n) for n in range(20)]
        + [pair("2024-09-01", "html", n) for n in range(3)]
        + [pair("2025-06-01", "html", n) for n in range(4)]
        + [pair("2026-10-01", "html", n) for n in range(5)]
    )
    splits = pairs.split(sorted(rows, key=lambda p: (p.date_reported, p.pair_id)))
    sizes = {name: len(rows) for name, rows in splits.items()}
    assert sizes == {"train": 21, "validation": 4, "test": 5, "legacy_holdout": 2}
    stats = pairs.write(splits, Counter(), tmp_path / "t3")
    assert stats["splits"]["test"]["rows"] == 5  # type: ignore[index]
    first = json.loads((tmp_path / "t3" / "train.jsonl").read_text().splitlines()[0])
    assert set(first) == {
        "pair_id",
        "dataset",
        "source_ref",
        "layout",
        "date_reported",
        "source",
        "target",
    }


def test_presidio_screen_finds_a_name_but_not_buildings() -> None:
    screen = PersonScreen()
    assert screen.has_person("Reported by Jane Doe at the front desk.")
    assert not screen.has_person("general location: SAMPLE HALL - On Campus disposition: OPEN CASE")


def test_committed_notebook_matches_its_builder() -> None:
    import build_t3_notebook

    assert build_t3_notebook.NOTEBOOK.read_text() == build_t3_notebook.build()


def test_notebook_embeds_schema_and_scorer_and_has_no_outputs() -> None:
    import build_t3_notebook

    notebook = json.loads(build_t3_notebook.build())
    code = "".join("".join(cell["source"]) for cell in notebook["cells"])
    assert "SYSTEM_PROMPT = (" in code and "def score(" in code
    assert "from campus_safety" not in code
    assert all(cell.get("outputs", []) == [] for cell in notebook["cells"])


def test_log_run_and_kaggle_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mlflow

    from campus_safety.t3 import cli, track

    monkeypatch.setattr(track, "TRACKING", tmp_path / "mlruns")
    outputs = tmp_path / "t3_outputs"
    outputs.mkdir()
    metrics = {
        "baseline": {"test": {"valid_json_rate": 0.5, "rows": 10.0}},
        "finetuned": {"test": {"valid_json_rate": 0.99, "rows": 10.0}},
    }
    (outputs / "metrics.json").write_text(json.dumps(metrics))
    (outputs / "run_info.json").write_text(
        json.dumps({"gpu": "Tesla T4", "hyperparameters": {"lora_r": 16}, "train_seconds": 60})
    )
    (outputs / "errors_finetuned_test.json").write_text("{}")
    assert cli.track_kaggle(outputs) == 0

    mlflow.set_tracking_uri((tmp_path / "mlruns").resolve().as_uri())
    (run,) = mlflow.search_runs(experiment_names=[track.EXPERIMENT], output_format="list")
    assert run.data.metrics["finetuned.test.valid_json_rate"] == pytest.approx(0.99)
    assert run.data.metrics["train_seconds"] == 60
    assert run.data.params["hyperparameters.lora_r"] == "16"
    assert run.data.params["gpu"] == "Tesla T4"
