"""T1 honesty switch: the trained model is used only when it beats both baselines (the same night
last week, and the rule) on the test years. Otherwise the rule is used, and the page says so.
The scorecard records the decision with every score; it holds numbers only, never records."""

import json
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

Scores = dict[str, float]
KEYS = {
    "method",  # model | rule
    "model",  # glm | lightgbm | null
    "scores",  # {"model": {...} | null, "rule": {...}, "last_week": {...}} on the test years
    "event_multiplier",
    "split_rows",
    "versions",
    "run_id",
    "trained_at",
}


def decide(model: Scores | None, rule: Scores, last_week: Scores) -> str:
    if model is None:
        return "rule"
    best_baseline = min(rule["deviance"], last_week["deviance"])
    return "model" if model["deviance"] < best_baseline else "rule"


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "absent"


def scorecard(
    *,
    run_id: str,
    trained_at: datetime,
    model_name: str | None,
    model: Scores | None,
    rule: Scores,
    last_week: Scores,
    multiplier: float,
    split_rows: dict[str, int],
) -> dict[str, Any]:
    method = decide(model, rule, last_week)
    return {
        "method": method,
        "model": model_name if model is not None else None,
        "scores": {"model": model, "rule": rule, "last_week": last_week},
        "event_multiplier": multiplier,
        "split_rows": split_rows,
        "versions": {p: _version(p) for p in ("campus-safety-signal", "lightgbm", "scikit-learn")},
        "run_id": run_id,
        "trained_at": trained_at.isoformat(),
    }


def validate(card: dict[str, Any]) -> None:
    if set(card) != KEYS:
        raise ValueError(f"scorecard keys differ: {sorted(set(card) ^ KEYS)}")
    if card["method"] not in {"model", "rule"}:
        raise ValueError("scorecard method must be model or rule")
    if card["method"] == "model" and card["model"] not in {"glm", "lightgbm"}:
        raise ValueError("a model scorecard must name glm or lightgbm")


def write(card: dict[str, Any], path: Path) -> None:
    validate(card)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
