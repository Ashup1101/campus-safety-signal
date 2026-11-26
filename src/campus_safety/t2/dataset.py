"""T2 dataset: news item title + short summary, labeled relevant or not. Hand-checked labels
(data/manual/news_ground_truth.yaml, the owner's gate 2) beat rule-made "weak" labels; weak labels
train but never test. The newest items form the test set (time split). Without hand-checked labels
the test set is empty and any run is provisional. Article bodies are never used."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

GROUND_TRUTH = Path(__file__).resolve().parents[3] / "data" / "manual" / "news_ground_truth.yaml"
MAX_CHARS = 600  # title + the feed's own short summary; more is never needed
FIELDS = {"item_id", "title", "summary", "published_at", "relevant"}


@dataclass(frozen=True)
class Row:
    item_id: str
    published_at: datetime
    text: str
    label: bool
    weak: bool  # True: the rule's label, not hand-checked


@dataclass
class Dataset:
    train: list[Row] = field(default_factory=list)
    test: list[Row] = field(default_factory=list)

    @property
    def provisional(self) -> bool:
        return not self.test


def ground_truth(path: Path = GROUND_TRUTH) -> dict[str, bool]:
    if not path.exists():
        return {}
    entries = (yaml.safe_load(path.read_text()) or {}).get("items", [])
    return {str(e["item_id"]): bool(e["relevant"]) for e in entries}


def text_of(item: Mapping[str, Any]) -> str:
    return f"{item.get('title') or ''}. {item.get('summary') or ''}".strip()[:MAX_CHARS]


def build(
    items: Iterable[Mapping[str, Any]], truth: Mapping[str, bool], test_share: float = 0.3
) -> Dataset:
    rows = []
    for item in items:
        if set(item) - FIELDS:
            raise ValueError("only title and summary are used, never an article body")
        item_id = str(item["item_id"])
        checked = item_id in truth
        label = truth[item_id] if checked else bool(item["relevant"])
        rows.append(Row(item_id, item["published_at"], text_of(item), label, not checked))
    rows.sort(key=lambda r: (r.published_at, r.item_id))
    cut = len(rows) - round(len(rows) * test_share)
    found = Dataset(train=rows[:cut])
    found.test = [r for r in rows[cut:] if not r.weak]
    return found
