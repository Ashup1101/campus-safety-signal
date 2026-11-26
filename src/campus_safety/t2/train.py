"""T2 training (GitHub Actions only, `train` dependency group): TF-IDF + logistic regression on the
T2 dataset, compared with the rule on the hand-checked test set at the rule's recall. The model is
used only if it is more precise there; otherwise (or with no test set) the rules stay."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from campus_safety.t2.dataset import Dataset, Row
from campus_safety.t2.model import score, tokens


def _precision_recall(predicted: Sequence[bool], actual: Sequence[bool]) -> tuple[float, float]:
    hits = sum(p and a for p, a in zip(predicted, actual, strict=True))
    shown, wanted = sum(predicted), sum(actual)
    return (hits / shown if shown else 0.0, hits / wanted if wanted else 0.0)


def fit(train: Sequence[Row]) -> dict[str, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    vectorizer = TfidfVectorizer(analyzer=tokens, sublinear_tf=True, min_df=1)
    x = vectorizer.fit_transform([r.text for r in train])
    model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=0)
    model.fit(x, [r.label for r in train])
    return {
        "vocabulary": {t: int(i) for t, i in vectorizer.vocabulary_.items()},
        "idf": [float(v) for v in vectorizer.idf_],
        "coef": [float(v) for v in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "threshold": 0.5,
    }


def at_recall(
    scores: Sequence[float], actual: Sequence[bool], recall: float
) -> tuple[float, float]:
    """(threshold, precision): the highest threshold whose recall reaches `recall`."""
    for threshold in sorted(set(scores), reverse=True):
        predicted = [s >= threshold for s in scores]
        precision, got = _precision_recall(predicted, actual)
        if got >= recall:
            return threshold, precision
    return 0.0, _precision_recall([True] * len(scores), actual)[0]


def scorecard(
    data: Dataset, rule: Sequence[bool], run_id: str, weights: dict[str, Any]
) -> dict[str, Any]:
    """rule: the rule's label for each test row (same order)."""
    card: dict[str, Any] = {
        "run_id": run_id,
        "trained_at": datetime.now(UTC).isoformat(),
        "train_rows": len(data.train),
        "weak_train_rows": sum(r.weak for r in data.train),
        "test_rows": len(data.test),
        "provisional": data.provisional,
        "method": "rules",
        "scores": {},
    }
    if data.provisional:
        return card
    actual = [r.label for r in data.test]
    rule_precision, rule_recall = _precision_recall(rule, actual)
    threshold, precision = at_recall(
        [score(weights, r.text) for r in data.test], actual, rule_recall
    )
    weights["threshold"] = threshold
    card["scores"] = {
        "rules": {"precision": rule_precision, "recall": rule_recall},
        "model": {"precision": precision, "recall_target": rule_recall, "threshold": threshold},
    }
    card["method"] = "model" if precision > rule_precision else "rules"
    return card


def run(data: Dataset, rule: Sequence[bool], run_id: str, out: Path) -> dict[str, Any]:
    weights = fit(data.train)
    card = scorecard(data, rule, run_id, weights)
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(json.dumps(weights))
    (out / "scorecard.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return card
