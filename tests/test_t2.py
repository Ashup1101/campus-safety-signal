"""T2 news relevance: dataset rules (time split, weak labels never in test, no article bodies).
Made-up items."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from campus_safety.t2 import dataset

T0 = datetime(2026, 9, 1)


def item(n: int, title: str, relevant: bool, summary: str = "") -> dict[str, object]:
    return {
        "item_id": f"i{n}",
        "title": title,
        "summary": summary,
        "published_at": T0 + timedelta(days=n),
        "relevant": relevant,
    }


ITEMS = [
    item(n, f"Robbery near Kirkwood {n}" if n % 2 else f"Concert review {n}", bool(n % 2))
    for n in range(10)
]


def test_weak_labels_train_and_only_hand_checked_labels_test() -> None:
    truth = {"i8": True, "i9": False, "i1": True}
    found = dataset.build(ITEMS, truth, test_share=0.3)
    assert [r.item_id for r in found.test] == ["i8", "i9"]  # newest 30%, hand-checked only
    assert all(not r.weak for r in found.test)
    assert {r.item_id: r.weak for r in found.train}["i1"] is False  # truth wins over the rule
    assert {r.item_id for r in found.train} == {f"i{n}" for n in range(7)}  # i7 weak: dropped
    assert found.provisional is False


def test_without_hand_checked_labels_the_test_is_empty_and_provisional() -> None:
    found = dataset.build(ITEMS, {}, test_share=0.3)
    assert found.test == [] and found.provisional is True


def test_text_is_title_and_a_short_summary_never_a_body() -> None:
    long = item(0, "Theft on 10th", True, summary="x" * 5000)
    [row] = dataset.build([long], {}, test_share=0.0).train
    assert row.text.startswith("Theft on 10th") and len(row.text) <= dataset.MAX_CHARS
    with pytest.raises(ValueError, match="body"):
        dataset.build([{**long, "body": "full article"}], {}, test_share=0.0)


def test_ground_truth_file(tmp_path: Path) -> None:
    path = tmp_path / "truth.yaml"
    path.write_text(
        "items:\n  - {item_id: i1, relevant: true}\n  - {item_id: i2, relevant: false}\n"
    )
    assert dataset.ground_truth(path) == {"i1": True, "i2": False}
    assert dataset.ground_truth(tmp_path / "missing.yaml") == {}
