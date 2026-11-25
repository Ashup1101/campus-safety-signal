"""T1 models on a small made-up table. Runs in CI (train group); skipped on the laptop."""

import random
from datetime import date, timedelta

import pytest

from campus_safety.t1 import baselines
from campus_safety.t1.baselines import Row

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from campus_safety.t1 import train


def fixture_rows() -> list[Row]:
    rng = random.Random(7)  # noqa: S311 (made-up test data, not security)
    rows = []
    for zone, rate in (("LB1", 0.2), ("LB2", 1.0), ("LB3", 2.5)):
        night = date(2021, 1, 1)
        while night <= date(2026, 6, 30):
            event = night.month == 10 and night.day == 31
            mean = rate * (1.6 if night.weekday() >= 4 else 1.0) * (3.0 if event else 1.0)
            calls = sum(rng.random() < mean / 10 for _ in range(10))
            rows.append(Row(zone, night, calls, night.weekday(), night.month, event, calls, rate))
            night += timedelta(days=1)
    return rows


def test_fit_picks_a_candidate_and_scores_validation_and_test() -> None:
    parts = baselines.split(fixture_rows())
    fitted = train.fit(parts)
    assert fitted.name in {"glm", "lightgbm"}
    assert fitted.validation["rows"] == len(parts["validation"])
    assert fitted.test["deviance"] >= 0
    predictions = fitted.predict(parts["test"][:5])
    assert all(p > 0 for p in predictions)


def test_fit_is_deterministic() -> None:
    parts = baselines.split(fixture_rows())
    first, second = train.fit(parts), train.fit(parts)
    assert first.name == second.name
    assert first.test == second.test
