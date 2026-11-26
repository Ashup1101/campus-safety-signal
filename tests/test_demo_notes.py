"""Community notes on the demo server. Made-up accounts, incidents and words."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from demo_server.seed import ACCOUNTS
from demo_server.store import Store

NOW = datetime(2026, 11, 26, 23, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "demo.sqlite3")
    for account in ACCOUNTS:
        store.add_account(account)
    return store


def test_notes_tables_hold_no_location(store: Store, tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "demo.sqlite3")
    for table in ("notes", "note_reports", "bans", "settings"):
        columns = {row[1] for row in db.execute(f"pragma table_info({table})")}
        assert columns, table
        assert not columns & {"lat", "lon", "latitude", "longitude", "location", "distance_m"}


def test_one_note_per_person_per_incident(store: Store) -> None:
    first = store.put_note("t1", "student_sam", "Police on scene", None, "pending", NOW)
    again = store.put_note("t1", "student_sam", "Road closed", "Dunn closed", "pending", NOW)
    assert first == again  # an edit, not a second note
    [note] = store.notes_of("t1")
    assert (note["tag"], note["text"], note["account_id"]) == (
        "Road closed",
        "Dunn closed",
        "student_sam",
    )
    store.set_note_state(first, "hidden")
    assert store.note(first)["state"] == "hidden"  # type: ignore[index]
    assert store.delete_note(first) and store.notes_of("t1") == []


def test_reports_bans_settings_and_delete(store: Store) -> None:
    note = store.put_note("t1", "student_sam", "Police on scene", None, "visible", NOW)
    assert store.add_report(note, "student_alex") and not store.add_report(note, "student_alex")
    assert store.report_count(note) == 1
    store.ban("student_sam", NOW + timedelta(days=7))
    assert store.banned("student_sam", NOW) and not store.banned(
        "student_sam", NOW + timedelta(days=8)
    )
    assert store.setting("notes_enabled", "on") == "on"
    store.set_setting("notes_enabled", "off")
    assert store.setting("notes_enabled", "on") == "off"
    sam = store.account("student_sam")
    assert sam is not None
    store.delete_account(sam)
    assert store.notes_of("t1") == [] and not store.banned("student_sam", NOW)
