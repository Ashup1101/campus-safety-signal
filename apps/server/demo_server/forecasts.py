"""The console's Forecasts section from the newest imported T1 run (gold.tonight) and its
scorecard. Counts of calls for service, which are not crimes; every forecast names its method.
Nothing is invented: no imported run means empty sections, and "tonight" is empty when the run
does not cover tonight (it starts the night after the city's newest data)."""

import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from campus_safety.events import Event
from campus_safety.lake.storage import Lake

NOTE = "Expected calls for service per police zone, not crimes. Each forecast names its method."
METHOD_WORDS = {"model": "forecast model", "rule": "simple rule"}
OUTLOOK_NIGHTS = 7


def scorecard(lake: Lake, run_id: str) -> dict[str, Any] | None:
    """Numbers from the run's scorecard: method, model, trained date, scores vs both baselines."""
    key = f"t1/{run_id}/scorecard.json"
    if key not in lake.keys(f"t1/{run_id}/"):
        return None
    card = json.loads(lake.get(key))
    return {k: card[k] for k in ("method", "model", "trained_at", "scores", "split_rows")}


def build(
    rows: Sequence[dict[str, Any]],
    card: dict[str, Any] | None,
    calendar: Sequence[Event],
    tonight: date,
) -> dict[str, Any]:
    """rows: gold.tonight late-night rows (zonecode, night, expected, level, method, reason,
    run_id) for one run."""
    events = {night: e.name for e in calendar for night in e.nights}
    nights = sorted({r["night"] for r in rows})[:OUTLOOK_NIGHTS]
    method = rows[0]["method"] if rows else None
    zones: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["night"] in nights:
            zones.setdefault(r["zonecode"], []).append(
                {"night": r["night"], "expected": r["expected"], "level": r["level"]}
            )
    return {
        "note": NOTE,
        "run_id": rows[0]["run_id"] if rows else None,
        "method": method,
        "method_words": METHOD_WORDS.get(method or ""),
        "tonight": {
            "night": tonight if tonight in nights else None,
            "zones": [
                {k: r[k] for k in ("zonecode", "expected", "level", "reason")}
                for r in rows
                if r["night"] == tonight
            ],
        },
        "outlook": {
            "nights": [
                {
                    "night": night,
                    "event": events.get(night),
                    "campus_expected": round(
                        sum(r["expected"] for r in rows if r["night"] == night), 1
                    ),
                }
                for night in nights
            ],
            "zones": [{"zonecode": z, "nights": found} for z, found in sorted(zones.items())],
        },
        "scorecard": card,
    }
