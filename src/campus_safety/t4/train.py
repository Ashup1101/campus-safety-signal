"""T4 training (GitHub Actions only, `train` group): the T2 text classifier fitted on attacks vs
harmless text. Scored as recall on unseen attack families with at most 2% false alarms on
harmless test text, against the existing injection pattern. An extra gate, never the only one."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from campus_safety.news.screen import INJECTION
from campus_safety.t2 import train as t2_train
from campus_safety.t2.model import score
from campus_safety.t4.dataset import Dataset

MAX_FALSE_ALARMS = 0.02


def rule_flags(text: str) -> bool:
    return INJECTION.search(text) is not None


def recall_at_fp(
    scores: Sequence[float], labels: Sequence[bool], max_fp: float
) -> tuple[float, float]:
    """(threshold, recall): the lowest threshold whose false-alarm rate on harmless rows stays
    within max_fp. 1.01 and 0.0 when none does."""
    harmless = sum(not label for label in labels) or 1
    attacks = sum(labels) or 1
    best = (1.01, 0.0)
    for threshold in sorted(set(scores), reverse=True):
        flagged = [s >= threshold for s in scores]
        false_alarms = sum(f and not label for f, label in zip(flagged, labels, strict=True))
        if false_alarms / harmless > max_fp:
            break
        best = (
            threshold,
            sum(f and label for f, label in zip(flagged, labels, strict=True)) / attacks,
        )
    return best


def run(data: Dataset, run_id: str, out: Path) -> dict[str, Any]:
    weights = t2_train.fit(data.train)
    labels = [r.label for r in data.test]
    threshold, recall = recall_at_fp(
        [score(weights, r.text) for r in data.test], labels, MAX_FALSE_ALARMS
    )
    rule = [rule_flags(r.text) for r in data.test]
    harmless = sum(not label for label in labels) or 1
    rule_recall = sum(f and label for f, label in zip(rule, labels, strict=True)) / (
        sum(labels) or 1
    )
    rule_fp = sum(f and not label for f, label in zip(rule, labels, strict=True)) / harmless
    weights["threshold"] = threshold
    card = {
        "run_id": run_id,
        "trained_at": datetime.now(UTC).isoformat(),
        "train_rows": len(data.train),
        "test_rows": len(data.test),
        "scores": {
            "rules": {"recall": rule_recall, "false_alarm_rate": rule_fp},
            "model": {
                "recall": recall,
                "threshold": threshold,
                "max_false_alarms": MAX_FALSE_ALARMS,
            },
        },
        # The model keeps false alarms within 2% by its threshold; it must also catch more.
        "method": "model" if recall > rule_recall else "rules",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(json.dumps(weights))
    (out / "scorecard.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return card
