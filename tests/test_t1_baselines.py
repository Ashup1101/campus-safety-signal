"""T1 time split, baselines and metrics. Made-up rows."""

import math
from datetime import date
from pathlib import Path

import duckdb
import pytest

from campus_safety.t1 import baselines, metrics
from campus_safety.t1.baselines import Row


def row(
    night: date, calls: int, last_week: int = 1, mean_4w: float = 0.5, event: bool = False
) -> Row:
    return Row("LB101", night, calls, night.weekday(), night.month, event, last_week, mean_4w)


def test_split_by_year_without_overlap() -> None:
    rows = [row(date(2023, 12, 31), 1), row(date(2024, 1, 1), 1), row(date(2024, 12, 31), 1)]
    rows += [row(date(2025, 1, 1), 1), row(date(2026, 10, 1), 1)]
    found = baselines.split(rows)
    assert [len(found[k]) for k in ("train", "validation", "test")] == [1, 2, 2]
    assert max(r.night for r in found["train"]) < min(r.night for r in found["validation"])
    assert max(r.night for r in found["validation"]) < min(r.night for r in found["test"])


def test_metrics_poisson_deviance_and_mae() -> None:
    assert metrics.poisson_deviance([0, 2], [1.0, 1.0]) == pytest.approx(
        2 * (1 + 2 * math.log(2) - 1) / 2
    )
    assert metrics.mae([0, 2], [1.0, 1.0]) == 1.0
    # A zero prediction is floored so deviance stays finite.
    assert math.isfinite(metrics.poisson_deviance([1], [0.0]))


def test_baselines_last_week_and_the_rule() -> None:
    normal = [row(date(2023, 3, d), 1) for d in range(1, 11)]
    events = [row(date(2023, 10, 31), 3, event=True)]
    multiplier = baselines.event_multiplier(normal + events)
    assert multiplier == 3.0  # 3 calls on event nights vs 1 on normal nights
    tonight = row(date(2025, 10, 31), 0, last_week=2, mean_4w=0.5, event=True)
    assert baselines.last_week(tonight) == 2.0
    assert baselines.rule(tonight, multiplier) == 1.5
    assert baselines.rule(row(date(2025, 11, 4), 0, mean_4w=0.0), multiplier) == metrics.FLOOR


def test_load_drops_rows_without_history(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    duckdb.execute(
        "COPY (SELECT * FROM (VALUES"
        " ('LB1', DATE '2024-01-01', 'late_night', 1, 0, 1, false, NULL, NULL),"
        " ('LB1', DATE '2024-02-01', 'late_night', 2, 3, 2, true, 1, 0.5)"
        ') AS t(zonecode, night, "window", calls, weekday, month, is_event, last_week, mean_4w))'
        " TO $p (FORMAT parquet)",
        {"p": str(path)},
    )
    assert baselines.load(path) == [Row("LB1", date(2024, 2, 1), 2, 3, 2, True, 1, 0.5)]
