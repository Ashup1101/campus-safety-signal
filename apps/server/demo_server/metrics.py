"""Alert metrics for the IUPD console, over the last N days. Counts and times only.

- Delivery time: from when the server received an alert to when a device showed it, per device
  type (web, ios), as the median and the 95th percentile (nearest rank) over deliveries.
- Alerts: IU's own alerts received in the period plus engine alerts (one per incident card).
- Corrections: incident cards that got a correction. Duplicates: the same account shown the same
  words twice on one card (per device type), or the same follow-up twice in its mailbox.
Rates are per 100 alerts; with no alerts they are None, not errors.
"""

import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from demo_server.store import Store

CLIENTS = ("web", "ios")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(q / 100 * len(ordered)), 1) - 1]


def per_100(count: int, alerts: int) -> float | None:
    return round(100 * count / alerts, 1) if alerts else None


def alert_metrics(store: Store, now: datetime, days: int) -> dict[str, Any]:
    since = now - timedelta(days=days)
    deliveries, official, mail = store.metric_rows()
    recent = {a for a, received in official if datetime.fromisoformat(received) >= since}
    seconds: dict[str, list[float]] = {client: [] for client in CLIENTS}
    shown: Counter[tuple[str, str, str, str]] = Counter()
    for account_id, client, shown_at, alert_id, thread_id, text, received in deliveries:
        if alert_id in recent:
            delay = datetime.fromisoformat(shown_at) - datetime.fromisoformat(received)
            seconds[client].append(delay.total_seconds())
            shown[(account_id, client, thread_id, text)] += 1
    followups = [
        (account_id, kind, thread_id, words)
        for account_id, kind, thread_id, words, created in mail
        if datetime.fromisoformat(created) >= since
    ]
    alerts = len(recent) + len({thread for _, kind, thread, _ in followups if kind == "alert"})
    corrections = len({thread for _, kind, thread, _ in followups if kind == "correction"})
    duplicates = sum(n - 1 for n in shown.values()) + sum(
        n - 1 for n in Counter(followups).values()
    )
    return {
        "days": days,
        "alerts": alerts,
        "latency": {
            client: {
                "median_s": percentile(values, 50),
                "p95_s": percentile(values, 95),
                "deliveries": len(values),
            }
            for client, values in seconds.items()
        },
        "corrections": corrections,
        "corrections_per_100": per_100(corrections, alerts),
        "duplicates": duplicates,
        "duplicates_per_100": per_100(duplicates, alerts),
    }
