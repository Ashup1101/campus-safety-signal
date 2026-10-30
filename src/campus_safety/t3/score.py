"""Score extractions: valid-JSON rate and field-level exact match against the parsed targets.

Dependency-free like schema.py; the notebook embeds it so local and Kaggle numbers are computed
by the same code.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from campus_safety.t3.schema import FIELDS

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def parse_output(text: str) -> dict[str, object] | None:
    """The JSON object in a model's answer, or None. A single ``` fence is tolerated."""
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    try:
        value = json.loads(fenced[1] if fenced else stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _norm(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split())


@dataclass
class Report:
    rows: int = 0
    valid_json: int = 0
    exact: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    all_fields: int = 0
    errors: dict[str, list[int]] = field(default_factory=lambda: {f: [] for f in FIELDS})

    def summary(self) -> dict[str, float]:
        n = max(self.rows, 1)
        out = {"rows": float(self.rows), "valid_json_rate": self.valid_json / n}
        out.update({f"exact_{name}": count / n for name, count in self.exact.items()})
        out["exact_all_fields"] = self.all_fields / n
        return out


def score(outputs: Sequence[str], targets: Sequence[Mapping[str, object]]) -> Report:
    """An invalid answer counts as wrong on every field. `errors` holds row indices per field."""
    report = Report(rows=len(targets))
    for index, (text, expected) in enumerate(zip(outputs, targets, strict=True)):
        got = parse_output(text)
        if got is not None:
            report.valid_json += 1
        right = 0
        for name in FIELDS:
            if got is not None and _norm(got.get(name)) == _norm(expected.get(name)):
                report.exact[name] += 1
                right += 1
            else:
                report.errors[name].append(index)
        report.all_fields += right == len(FIELDS)
    return report
