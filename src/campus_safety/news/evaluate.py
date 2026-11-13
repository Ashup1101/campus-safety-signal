"""Per-field precision and recall of an extractor against the owner's ground truth.

Ground truth (data/manual/news_ground_truth.yaml, local only):

    records:
      - url: https://outlet.example/story
        incident_type: shooting          # one of extract.TYPES, or null
        occurred_date: 2026-11-01
        occurred_time: "01:30"
        location_text: 400 block of E. Kirkwood Avenue
        injuries: 7
        deaths: 0
        weapon_involved: true
        iu_related: true

Scoring per field: a predicted value counts as a true positive when it equals the truth, a
false positive when it is set but differs, and a false negative when the truth is set and the
prediction is not. Reports carry counts only, never item text.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from campus_safety.news.extract import FIELDS, Extraction, Extractor
from campus_safety.news.items import Item
from campus_safety.news.screen import screen

TRUTH = Path("data", "manual", "news_ground_truth.yaml")
_PUNCT = re.compile(r"[^a-z0-9]+")


@dataclass
class FieldScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0


@dataclass
class Report:
    extractor: str
    records: int = 0
    missing_items: int = 0  # ground-truth URLs not in bronze
    no_answer: int = 0
    fields: dict[str, FieldScore] = field(default_factory=lambda: {f: FieldScore() for f in FIELDS})


def load_truth(path: Path = TRUTH) -> list[dict[str, object]]:
    records = (yaml.safe_load(path.read_text()) or {}).get("records", [])
    if not isinstance(records, list):
        raise ValueError("ground truth must hold a records list")
    return [dict(r) for r in records]


def _norm(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool | int):
        return value
    if isinstance(value, date):
        return value.isoformat()
    return _PUNCT.sub(" ", str(value).lower()).strip() or None


def score_one(report: Report, got: Extraction | None, truth: Mapping[str, object]) -> None:
    if got is None:
        report.no_answer += 1
    answer = got.to_json() if got else dict.fromkeys(FIELDS)
    for name in FIELDS:
        expected, predicted = _norm(truth.get(name)), _norm(answer.get(name))
        if name == "iu_related":  # always set on both sides
            expected, predicted = bool(expected), bool(predicted)
        score = report.fields[name]
        if predicted is not None and predicted == expected:
            score.tp += 1
            continue
        if predicted is not None:
            score.fp += 1
        if expected is not None:
            score.fn += 1


def evaluate(
    extractor: Extractor, truth: Iterable[Mapping[str, object]], found: Mapping[str, Item]
) -> Report:
    """`found` maps item URLs to bronze items."""
    report = Report(extractor.name)
    for record in truth:
        report.records += 1
        item = found.get(str(record.get("url", "")))
        if item is None:
            report.missing_items += 1
            continue
        got = extractor.extract(screen(item.text).text, item.published_at)
        score_one(report, got, record)
    return report


def lines(report: Report) -> list[str]:
    out = [
        f"{report.extractor}: {report.records} records, {report.missing_items} not in bronze,"
        f" {report.no_answer} without an answer"
    ]
    out.extend(
        f"  {name:<16} P {s.precision:.2f}  R {s.recall:.2f}  (tp {s.tp}, fp {s.fp}, fn {s.fn})"
        for name, s in report.fields.items()
    )
    return out
