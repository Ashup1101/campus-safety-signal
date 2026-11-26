"""Pilot metrics for the console (Sprint 11): counts, medians and averages, never a person."""

from datetime import UTC, datetime
from pathlib import Path

from demo_target import store_at

from demo_server import consents, pilot
from demo_server.seed import ACCOUNTS
from demo_server.store import Store


def test_pilot_numbers_never_name_anyone(tmp_path: Path) -> None:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    now = datetime.now(UTC)
    store.set_consent("student_sam", "sharing", True, consents.VERSION, now)
    store.set_consent("student_alex", "sharing", False, consents.VERSION, now)
    store.add_survey_answer("student_sam", "signup", [5, 4, 3], now)
    store.add_survey_answer("parent_mom", "signup", [3, 4, 5], now)
    store.add_survey_answer("parent_dad", "signup", None, now)  # skipped
    found = pilot.metrics(store, now)
    assert found["opt_in"]["sharing"] == {"granted": 1, "declined": 1, "withdrawn": 0}
    assert found["surveys"]["signup"] == {"answers": 2, "skipped": 1, "means": [4.0, 4.0, 4.0]}
    assert "alerts" in found and "latency" in found["alerts"]
    assert "student_sam" not in str(found) and "Sam" not in str(found)
