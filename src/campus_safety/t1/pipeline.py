"""One T1 run: score the baselines on the test years, optionally fit the models (Actions only),
apply the honesty switch, forecast the seven nights after the last data, and write
scorecard.json + forecast.parquet. Both files hold numbers and plain reasons only."""

from collections.abc import Sequence
from dataclasses import astuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

from campus_safety import events
from campus_safety.lake.parquet import Columns, write_parquet
from campus_safety.t1 import baselines, forecast, metrics, switch

FORECAST: Columns = (
    ("zonecode", "VARCHAR"),
    ("night", "DATE"),
    ("window", "VARCHAR"),
    ("expected", "DOUBLE"),
    ("level", "VARCHAR"),
    ("method", "VARCHAR"),
    ("reason", "VARCHAR"),
)


def _scores(rows: list[baselines.Row], predicted: list[float]) -> switch.Scores:
    actual = [float(r.calls) for r in rows]
    return {
        "deviance": metrics.poisson_deviance(actual, predicted),
        "mae": metrics.mae(actual, predicted),
        "rows": float(len(rows)),
    }


def run(table: Path, out: Path, run_id: str, fit_models: bool) -> dict[str, object]:
    rows = baselines.load(table)
    parts = baselines.split(rows)
    multiplier = baselines.event_multiplier(parts["train"])
    test = parts["test"]

    def rule(rs: Sequence[baselines.Row]) -> list[float]:
        return [baselines.rule(r, multiplier) for r in rs]

    rule_scores = _scores(test, rule(test))
    last_week_scores = _scores(test, [baselines.last_week(r) for r in test])
    fitted = None
    if fit_models:
        from campus_safety.t1 import train  # the train group, installed only on Actions

        fitted = train.fit(parts)
    card = switch.scorecard(
        run_id=run_id,
        trained_at=datetime.now(UTC),
        model_name=fitted.name if fitted else None,
        model=fitted.test if fitted else None,
        rule=rule_scores,
        last_week=last_week_scores,
        multiplier=multiplier,
        split_rows={name: len(part) for name, part in parts.items()},
    )
    use_model = card["method"] == "model" and fitted is not None
    predict = fitted.predict if use_model and fitted else rule
    start = max(r.night for r in rows) + timedelta(days=1)  # the night after the last data
    found = forecast.forecast(rows, start, predict, str(card["method"]), events.load())
    switch.write(card, out / "scorecard.json")
    write_parquet(out / "forecast.parquet", FORECAST, [astuple(f) for f in found])
    return card
