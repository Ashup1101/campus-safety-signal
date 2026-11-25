"""T1 models, trained on GitHub Actions only (never on the laptop): a Poisson GLM
(scikit-learn) and gradient-boosted trees with a Poisson objective (LightGBM). Both see the same
compact features; the one with the lower validation deviance is the candidate.

Needs the `train` dependency group (uv sync --group train)."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from campus_safety.t1 import metrics
from campus_safety.t1.baselines import Row

SEED = 0


@dataclass(frozen=True)
class Fitted:
    name: str  # glm | lightgbm
    predict: Callable[[Sequence[Row]], list[float]]
    validation: dict[str, float]
    test: dict[str, float]


def zone_rates(train: Sequence[Row]) -> dict[str, float]:
    """Each zone's mean calls per night on the training years (the zone's own level)."""
    totals: dict[str, list[int]] = {}
    for r in train:
        t = totals.setdefault(r.zonecode, [0, 0])
        t[0] += r.calls
        t[1] += 1
    return {z: calls / nights for z, (calls, nights) in totals.items()}


def features(rows: Sequence[Row], rates: dict[str, float]) -> np.ndarray:
    """weekday and month one-hot, event night, log last week, log 4-week mean, log zone rate."""
    fallback = sum(rates.values()) / len(rates) if rates else 0.0
    out = np.zeros((len(rows), 7 + 12 + 4), dtype=np.float64)
    for i, r in enumerate(rows):
        out[i, r.weekday] = 1.0
        out[i, 7 + r.month - 1] = 1.0
        out[i, 19] = 1.0 if r.is_event else 0.0
        out[i, 20] = math.log1p(r.last_week)
        out[i, 21] = math.log1p(r.mean_4w)
        out[i, 22] = math.log(max(rates.get(r.zonecode, fallback), metrics.FLOOR))
    return out


def _scores(model: Any, rows: Sequence[Row], rates: dict[str, float]) -> dict[str, float]:
    actual = [float(r.calls) for r in rows]
    predicted = [float(p) for p in model.predict(features(rows, rates))]
    return {
        "deviance": metrics.poisson_deviance(actual, predicted),
        "mae": metrics.mae(actual, predicted),
        "rows": float(len(rows)),
    }


def fit(parts: dict[str, list[Row]]) -> Fitted:
    from lightgbm import LGBMRegressor
    from sklearn.linear_model import PoissonRegressor

    train, validation, test = parts["train"], parts["validation"], parts["test"]
    rates = zone_rates(train)
    x, y = features(train, rates), np.array([r.calls for r in train], dtype=np.float64)
    candidates = {
        "glm": PoissonRegressor(alpha=1e-4, max_iter=300),
        "lightgbm": LGBMRegressor(
            objective="poisson",
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=50,
            random_state=SEED,
            deterministic=True,
            force_col_wise=True,
            n_jobs=1,
            verbose=-1,
        ),
    }
    scored = []
    for name, model in candidates.items():
        model.fit(x, y)
        scored.append((_scores(model, validation, rates)["deviance"], name, model))
    _, name, best = min(scored, key=lambda s: (s[0], s[1]))

    def predict(rows: Sequence[Row]) -> list[float]:
        return [max(float(p), metrics.FLOOR) for p in best.predict(features(rows, rates))]

    return Fitted(name, predict, _scores(best, validation, rates), _scores(best, test, rates))
