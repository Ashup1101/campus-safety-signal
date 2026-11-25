"""T1 time split and the two baselines the model must beat: the same night last week, and the
rule (4-week mean, times the event-night multiplier on event nights)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from campus_safety.t1.metrics import FLOOR

TRAIN_END, VALIDATION_END = date(2023, 12, 31), date(2024, 12, 31)  # test: 2025 onward


@dataclass(frozen=True)
class Row:
    zonecode: str
    night: date
    calls: int
    weekday: int
    month: int
    is_event: bool
    last_week: int
    mean_4w: float


def load(path: Path) -> list[Row]:
    """Rows of the training table that have a full history (last week and 4-week mean)."""
    found = duckdb.execute(
        "SELECT zonecode, night, calls, weekday, month, is_event, last_week, mean_4w"
        " FROM read_parquet($p) WHERE last_week IS NOT NULL AND mean_4w IS NOT NULL"
        " ORDER BY zonecode, night",
        {"p": str(path)},
    )
    return [Row(*r) for r in found.fetchall()]


def split(rows: Iterable[Row]) -> dict[str, list[Row]]:
    found: dict[str, list[Row]] = {"train": [], "validation": [], "test": []}
    for r in rows:
        part = (
            "train"
            if r.night <= TRAIN_END
            else "validation"
            if r.night <= VALIDATION_END
            else "test"
        )
        found[part].append(r)
    return found


def event_multiplier(train: Iterable[Row]) -> float:
    """Mean calls on event nights over mean calls on other nights (training rows), at least 1."""
    event, normal = [0, 0], [0, 0]  # [calls, rows]
    for r in train:
        side = event if r.is_event else normal
        side[0] += r.calls
        side[1] += 1
    if not event[1] or not normal[1] or not normal[0]:
        return 1.0
    return max(1.0, (event[0] / event[1]) / (normal[0] / normal[1]))


def last_week(r: Row) -> float:
    return max(float(r.last_week), FLOOR)


def rule(r: Row, multiplier: float) -> float:
    return max(r.mean_4w * (multiplier if r.is_event else 1.0), FLOOR)
