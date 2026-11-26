"""Scoring with an exported T2/T4 text model on the laptop: plain Python over JSON weights (word
and word-pair TF-IDF, then logistic regression). No sklearn and no pickles at inference."""

import math
import re
from collections import Counter
from itertools import pairwise
from typing import Any

_TOKEN = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> list[str]:
    words = _TOKEN.findall(text.lower())
    return words + [f"{a} {b}" for a, b in pairwise(words)]


def score(weights: dict[str, Any], text: str) -> float:
    """Probability-like score in [0, 1] from exported weights:
    {"vocabulary": {term: index}, "idf": [...], "coef": [...], "intercept": float}."""
    vocabulary, idf, coef = weights["vocabulary"], weights["idf"], weights["coef"]
    counts = Counter(t for t in tokens(text) if t in vocabulary)
    values = {vocabulary[t]: (1 + math.log(n)) * idf[vocabulary[t]] for t, n in counts.items()}
    norm = math.sqrt(sum(v * v for v in values.values())) or 1.0
    z = float(weights["intercept"]) + sum(coef[i] * v / norm for i, v in values.items())
    return 1 / (1 + math.exp(-z))


def flags(weights: dict[str, Any], text: str) -> bool:
    return score(weights, text) >= float(weights["threshold"])
