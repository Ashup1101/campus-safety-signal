"""Pilot metrics for the IUPD console (Sprint 11): alert delivery (median and slowest-5% time,
reach, corrections, repeats), consent opt-in counts per feature, and survey averages. Counts,
medians and means only: no row ever names or identifies a person."""

from collections import Counter
from datetime import datetime
from statistics import mean
from typing import Any

from demo_server import consents
from demo_server import metrics as alert_numbers
from demo_server.store import Store


def metrics_of_surveys(store: Store) -> dict[str, dict[str, Any]]:
    by_kind: dict[str, list[tuple[Any, ...]]] = {}
    for prompt, *answers in store.survey_rows():
        by_kind.setdefault(str(prompt).split(":")[0], []).append(tuple(answers))
    found = {}
    for kind, rows in by_kind.items():
        answered = [r for r in rows if r[0] is not None]
        means = [round(mean(r[i] for r in answered), 2) for i in range(3)] if answered else []
        found[kind] = {
            "answers": len(answered),
            "skipped": len(rows) - len(answered),
            "means": means,
        }
    return found


def metrics_of_consents(store: Store) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {kind: Counter() for kind in consents.KINDS}
    for account in store.accounts():
        for kind, row in store.consents(account.id).items():
            if kind in counts:
                counts[kind][consents.state(row)] += 1
    return {k: {s: c[s] for s in ("granted", "declined", "withdrawn")} for k, c in counts.items()}


def metrics(store: Store, now: datetime, days: int = 30) -> dict[str, Any]:
    return {
        "days": days,
        "alerts": alert_numbers.alert_metrics(store, now, days),
        "reach": store.reach(),
        "opt_in": metrics_of_consents(store),
        "surveys": metrics_of_surveys(store),
    }
