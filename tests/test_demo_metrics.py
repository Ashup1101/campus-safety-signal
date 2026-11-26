"""Alert metrics for the console: delivery time per device type, corrections and repeats per 100
alerts. Made-up alerts only."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from demo_target import store_at

from campus_safety.official.alerts import OfficialAlert
from demo_server import metrics
from demo_server.seed import ACCOUNTS
from demo_server.store import Store


def test_percentiles_use_the_nearest_rank() -> None:
    assert metrics.percentile([], 50) is None
    assert metrics.percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert metrics.percentile([float(n) for n in range(1, 101)], 95) == 95.0
    assert metrics.percentile([5.0], 95) == 5.0


def test_rates_with_no_alerts_are_none_not_errors() -> None:
    assert metrics.per_100(0, 0) is None
    assert metrics.per_100(1, 4) == 25.0


def official(text: str = "Made-up alert.") -> OfficialAlert:
    return OfficialAlert(
        source="feed",
        kind="web_page",
        text=text,
        verification="official",
        official_at=None,
        status="Severe",
    )


def test_metrics_for_a_period(tmp_path: Path) -> None:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    now = datetime.now(UTC)
    old = now - timedelta(days=40)
    store.add_alert("a1", official(), now - timedelta(minutes=30), "t1")
    store.add_alert("a2", official(), now - timedelta(minutes=20), "t1")  # same text, same card
    store.add_alert("a0", official(), old, "t0")  # outside the 30 days
    for alert_id, received, web_s, ios_s in (
        ("a1", now - timedelta(minutes=30), 1, 4),
        ("a2", now - timedelta(minutes=20), 3, 2),
        ("a0", old, 100, 100),
    ):
        store.delivered(alert_id, "student_sam", "web", received + timedelta(seconds=web_s))
        store.delivered(alert_id, "student_sam", "ios", received + timedelta(seconds=ios_s))
    store.deliver_mail("k1", "parent_mom", "alert", "Alert", "x", "incident-9")
    store.deliver_mail("k2", "parent_mom", "correction", "Correction", "y", "incident-9")

    found = metrics.alert_metrics(store, now, days=30)
    assert found["alerts"] == 3  # two official alerts and one engine alert
    assert found["latency"]["web"] == {"median_s": 1.0, "p95_s": 3.0, "deliveries": 2}
    assert found["latency"]["ios"] == {"median_s": 2.0, "p95_s": 4.0, "deliveries": 2}
    assert (found["corrections"], found["corrections_per_100"]) == (1, 33.3)
    # Sam saw the same words twice on one card, on each device type.
    assert (found["duplicates"], found["duplicates_per_100"]) == (2, 66.7)


def test_metrics_with_no_alerts(tmp_path: Path) -> None:
    found = metrics.alert_metrics(Store(store_at(tmp_path)), datetime.now(UTC), days=7)
    assert found["alerts"] == 0
    assert found["latency"]["web"] == {"median_s": None, "p95_s": None, "deliveries": 0}
    assert found["corrections_per_100"] is None and found["duplicates_per_100"] is None
