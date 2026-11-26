"""Shared model registry (T2, T4, T3): write-once import with hashes, no pickles, and the honesty
switch read from each run's scorecard. Made-up model files."""

import json
from pathlib import Path

import pytest

from campus_safety.lake.storage import FileLake
from campus_safety.models import registry


def run_dir(
    path: Path, run_id: str = "gh-1", method: str = "model", model: str = "model.json"
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    card = {
        "run_id": run_id,
        "method": method,
        "trained_at": "2026-11-26T00:00:00+00:00",
        "scores": {},
    }
    (path / "scorecard.json").write_text(json.dumps(card))
    (path / model).write_text(json.dumps({"weights": [1, 2]}))
    return path


def test_import_is_write_once_and_the_newest_run_is_used(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    assert registry.latest(lake, "t2") is None
    assert registry.import_run(lake, "t2", run_dir(tmp_path / "a")) == "imported"
    assert registry.import_run(lake, "t2", run_dir(tmp_path / "a")) == "unchanged"
    other = run_dir(tmp_path / "b")
    (other / "model.json").write_text("{}")
    with pytest.raises(ValueError, match="different files"):
        registry.import_run(lake, "t2", other)
    registry.import_run(lake, "t2", run_dir(tmp_path / "c", "gh-2", "rules"))
    found = registry.latest(lake, "t2")
    assert found is not None and found.run_id == "gh-2" and registry.uses_model(found) is False
    first = registry.runs(lake, "t2")[0]
    assert json.loads(registry.read(lake, first, "model.json")) == {"weights": [1, 2]}


def test_tampered_files_and_pickles_are_refused(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    registry.import_run(lake, "t4", run_dir(tmp_path / "a"))
    found = registry.latest(lake, "t4")
    assert found is not None and registry.uses_model(found)
    lake.put("models/t4/gh-1/model.json", b'{"weights": [9]}')
    with pytest.raises(ValueError, match="hash"):
        registry.read(lake, found, "model.json")
    with pytest.raises(ValueError, match="file type"):
        registry.import_run(lake, "t4", run_dir(tmp_path / "p", "gh-9", model="model.pkl"))
    bad = run_dir(tmp_path / "m", "gh-8")
    (bad / "scorecard.json").write_text(json.dumps({"run_id": "gh-8", "method": "maybe"}))
    with pytest.raises(ValueError, match="scorecard"):
        registry.import_run(lake, "t4", bad)


def weights(**change: object) -> dict[str, object]:
    found: dict[str, object] = {
        "vocabulary": {"robbery": 0, "kirkwood": 1},
        "idf": [1.0, 2.0],
        "coef": [0.5, -0.5],
        "intercept": 0.1,
        "threshold": 0.5,
    }
    return {**found, **change}


def test_text_model_weights_are_checked_before_import(tmp_path: Path) -> None:
    from campus_safety.models import text_model

    assert text_model.problems(weights()) == []
    assert text_model.problems(weights(extra=1)) == ["unexpected keys"]
    assert text_model.problems(weights(idf=[1.0])) == ["lengths differ"]
    assert text_model.problems(weights(vocabulary={"case 2026012345": 0, "x": 1})) == [
        "a term looks like a record (long number or email)"
    ]


def test_cli_imports_once_and_refuses_bad_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from campus_safety.t2 import cli

    monkeypatch.setenv("LAKE_URI", FileLake(tmp_path / "lake").uri)
    good = run_dir(tmp_path / "good")
    (good / "model.json").write_text(json.dumps(weights()))
    assert cli.main(["import", str(good)]) == 0
    assert cli.main(["import", str(good)]) == 0  # unchanged
    bad = run_dir(tmp_path / "bad", "gh-2")
    (bad / "model.json").write_text(json.dumps(weights(vocabulary={"kim@example.test": 0, "y": 1})))
    assert cli.main(["import", str(bad)]) == 1
    assert [r.run_id for r in registry.runs(FileLake(tmp_path / "lake"), "t2")] == ["gh-1"]
