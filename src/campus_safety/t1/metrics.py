"""T1 metrics: mean Poisson deviance (the training objective) and mean absolute error."""

import math
from collections.abc import Sequence

FLOOR = 0.01  # predictions below this are floored so the deviance stays finite


def poisson_deviance(actual: Sequence[float], predicted: Sequence[float]) -> float:
    total = 0.0
    for y, mu in zip(actual, predicted, strict=True):
        mu = max(mu, FLOOR)
        total += (y * math.log(y / mu) if y > 0 else 0.0) - (y - mu)
    return 2 * total / len(actual) if actual else 0.0


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    pairs = list(zip(actual, predicted, strict=True))
    return sum(abs(y - mu) for y, mu in pairs) / len(pairs) if pairs else 0.0
