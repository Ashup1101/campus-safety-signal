"""t1 import: shape checks and write-once lake copy. Made-up forecasts."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from campus_safety.lake.parquet import write_parquet
from campus_safety.lake.storage import FileLake
from campus_safety.t1 import importer, pipeline, switch

SCORES = {"deviance": 0.4, "mae": 0.2, "rows": 10.0}


def run_dir(path: Path, method: str = "rule", extra: bool = False) -> Path:
    card = switch.scorecard(
        run_id="gh-1",
        trained_at=datetime(2026, 11, 25, tzinfo=UTC),
        model_name="lightgbm" if method == "model" else None,
        model={"deviance": 0.1, "mae": 0.1, "rows": 10.0} if method == "model" else None,
        rule=SCORES,
        last_week=SCORES,
        multiplier=1.5,
        split_rows={"train": 1, "validation": 1, "test": 1},
    )
    switch.write(card, path / "scorecard.json")
    columns = [*pipeline.FORECAST, *((("case_number", "VARCHAR"),) if extra else ())]
    row = [
        "LB1",
        date(2026, 11, 25),
        "late_night",
        0.5,
        "quiet",
        method,
        "About a usual night here",
    ]
    write_parquet(path / "forecast.parquet", columns, [row + (["x"] if extra else [])])
    return path


def test_import_is_write_once_and_repeatable(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    source = run_dir(tmp_path / "run")
    assert importer.import_run(lake, source) == "imported"
    assert sorted(lake.keys("t1/gh-1/")) == [
        "t1/gh-1/forecast.parquet",
        "t1/gh-1/import.json",
        "t1/gh-1/scorecard.json",
    ]
    assert importer.import_run(lake, source) == "unchanged"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"extra": True}, "columns"), ({"method": "model"}, "method")],
)
def test_bad_runs_are_refused(tmp_path: Path, kwargs: dict[str, object], message: str) -> None:
    source = run_dir(tmp_path / "run", **kwargs)  # type: ignore[arg-type]
    if kwargs.get("method") == "model":  # scorecard says model, forecast rows say rule
        write_parquet(
            source / "forecast.parquet",
            pipeline.FORECAST,
            [["LB1", date(2026, 11, 25), "late_night", 0.5, "quiet", "rule", "x"]],
        )
    with pytest.raises(ValueError, match=message):
        importer.import_run(FileLake(tmp_path / "lake"), source)


def test_cli_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_safety.t1 import cli

    monkeypatch.setenv("LAKE_URI", (tmp_path / "lake").as_uri())
    assert cli.main(["import", str(run_dir(tmp_path / "run"))]) == 0
    assert cli.main(["import", str(tmp_path / "missing")]) == 1
