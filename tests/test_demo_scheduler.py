"""Briefings and digests on time, once per key, with a fake clock. Made-up incidents."""

from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from campus_safety.events import Event
from demo_server.mailbox import MailboxChannel
from demo_server.scheduler import Scheduler
from demo_server.seed import ACCOUNTS, LINKS, ZONES
from demo_server.store import Store

HALLOWEEN = Event(
    "halloween_2026", "Halloween weekend", (date(2026, 10, 30), date(2026, 10, 31)), "x"
)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "demo.sqlite3")
    for account in ACCOUNTS:
        store.add_account(account)
    for parent, student, label in LINKS:
        store.link(parent, student, label)
    for account_id, zones in ZONES.items():
        for zone in zones:
            store.add_zone(account_id, zone)
    return store


def warehouse(path: Path, *points: tuple[str, str, datetime]) -> Path:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA gold")
        con.execute(
            "CREATE TABLE gold.incident_points (incident_type VARCHAR, severity_tier VARCHAR,"
            " occurred_from TIMESTAMP, lat DOUBLE, lon DOUBLE, street_objectid BIGINT)"
        )
        for kind, tier, at in points:
            con.execute(
                "INSERT INTO gold.incident_points VALUES (?, ?, ?, 39.1666, -86.5300, 3)",
                [kind, tier, at],
            )
    return path


def scheduler(store: Store, db: Path, now: datetime) -> Scheduler:
    names = {"street_3": "E Kirkwood Ave, 400 block (Grant to Dunn)"}
    return Scheduler(store, MailboxChannel(store), db, names, [HALLOWEEN], lambda: now)


def kinds(store: Store, account_id: str) -> list[str]:
    return [str(m["kind"]) + ":" + str(m["subject"]) for m in store.mailbox(account_id)]


def test_briefings_go_to_every_family_account_once_from_the_afternoon_before(
    store: Store, tmp_path: Path
) -> None:
    db = tmp_path / "none.duckdb"
    assert scheduler(store, db, datetime(2026, 10, 29, 14, 0)).tick() == 0
    on_time = scheduler(store, db, datetime(2026, 10, 29, 15, 5))
    assert on_time.tick() == 4  # Sam, Alex, Mom, Dad; never the console
    assert on_time.tick() == 0  # once per key
    assert kinds(store, "parent_mom") == [
        "briefing:Before Halloween weekend (Fri Oct 30 and Sat Oct 31)"
    ]
    assert store.mailbox("console") == []
    assert scheduler(store, db, datetime(2026, 11, 1, 15, 0)).tick() == 0  # event is over


def test_daily_digest_holds_lower_level_reports_in_the_watch_zone(
    store: Store, tmp_path: Path
) -> None:
    db = warehouse(
        tmp_path / "w.duckdb",
        ("THEFT FROM BUILDING LESS THAN $750", "low", datetime(2026, 11, 23, 22, 0)),
        ("ROBBERY", "high", datetime(2026, 11, 23, 23, 0)),  # alert level: not in a digest
    )
    assert scheduler(store, db, datetime(2026, 11, 24, 6, 59)).tick() == 0
    assert scheduler(store, db, datetime(2026, 11, 24, 7, 5)).tick() == 1
    mail = store.mailbox("parent_mom")
    assert [m["subject"] for m in mail] == ["Daily digest: Kirkwood Avenue"]
    assert "1 lower-level report near Kirkwood Avenue" in str(mail[0]["body"])
    assert "E Kirkwood Ave, 400 block" in str(mail[0]["body"])
    assert store.mailbox("parent_dad") == []  # the point is outside Dad's zone


def test_weekly_digest_on_monday(store: Store, tmp_path: Path) -> None:
    db = warehouse(tmp_path / "w.duckdb", ("VANDALISM", "low", datetime(2026, 11, 18, 21, 0)))
    assert scheduler(store, db, datetime(2026, 11, 23, 7, 30)).tick() == 1  # Monday
    assert [m["subject"] for m in store.mailbox("parent_mom")] == ["Weekly digest: Kirkwood Avenue"]
