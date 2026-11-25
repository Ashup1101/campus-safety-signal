"""T1 honesty switch and scorecard. Made-up scores."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from campus_safety.t1 import switch

RULE = {"deviance": 0.47, "mae": 0.23, "rows": 100.0}
LAST_WEEK = {"deviance": 1.08, "mae": 0.26, "rows": 100.0}


@pytest.mark.parametrize(
    ("model_deviance", "method"),
    [(0.40, "model"), (0.47, "rule"), (0.60, "rule"), (None, "rule")],
)
def test_the_model_is_used_only_when_it_beats_both_baselines(
    model_deviance: float | None, method: str
) -> None:
    model = (
        None if model_deviance is None else {"deviance": model_deviance, "mae": 0.2, "rows": 100.0}
    )
    assert switch.decide(model, RULE, LAST_WEEK) == method


def test_scorecard_has_a_fixed_shape_for_both_outcomes(tmp_path: Path) -> None:
    at = datetime(2026, 11, 25, 6, 0, tzinfo=UTC)
    for model in ({"deviance": 0.4, "mae": 0.2, "rows": 100.0}, None):
        card = switch.scorecard(
            run_id="run-1",
            trained_at=at,
            model_name="lightgbm" if model else None,
            model=model,
            rule=RULE,
            last_week=LAST_WEEK,
            multiplier=1.72,
            split_rows={"train": 10, "validation": 5, "test": 5},
        )
        switch.validate(card)
        path = tmp_path / "scorecard.json"
        switch.write(card, path)
        assert json.loads(path.read_text()) == card
    assert card["method"] == "rule" and card["model"] is None


def test_validate_rejects_missing_or_extra_keys() -> None:
    card = switch.scorecard(
        run_id="r",
        trained_at=datetime(2026, 11, 25, tzinfo=UTC),
        model_name=None,
        model=None,
        rule=RULE,
        last_week=LAST_WEEK,
        multiplier=1.0,
        split_rows={"train": 1, "validation": 1, "test": 1},
    )
    with pytest.raises(ValueError, match="keys"):
        switch.validate({**card, "case_number": "x"})
    with pytest.raises(ValueError, match="keys"):
        switch.validate({k: v for k, v in card.items() if k != "method"})
