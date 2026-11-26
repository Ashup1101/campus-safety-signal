"""T4 fit on the red-team corpus. Runs in CI (train group); skipped on the laptop."""

from pathlib import Path

import pytest

pytest.importorskip("sklearn")

from campus_safety.t4 import dataset, train


def test_run_writes_weights_and_an_honest_scorecard(tmp_path: Path) -> None:
    card = train.run(dataset.build(), "gh-1", tmp_path)
    assert card["method"] in ("model", "rules")
    assert card["scores"]["model"]["max_false_alarms"] == 0.02
    assert (tmp_path / "model.json").exists() and (tmp_path / "scorecard.json").exists()
