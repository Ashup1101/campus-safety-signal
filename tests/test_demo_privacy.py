"""Privacy sweep (v8): after sharing, check-ins, "Are you OK?" and "Arrived home" run through the
hub, no table holds a location, band or answer, and the logs name no one and nowhere. Made-up
accounts and coordinates."""

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_demo_server import FakePeer, account, hub_for

from demo_server import signing
from demo_server.seed import ACCOUNTS, LINKS
from demo_server.store import Store

LAT, LON = 39.123457, -86.512345  # made up, unusual digits to search for
WATCH_ZONE_COLUMNS = {("zones", "lat"), ("zones", "lon")}  # places a person chose, not movements


def scenario(store: Store) -> list[str]:
    async def run() -> list[str]:
        hub = hub_for(store)
        hub.clock.set("event_night")
        hub.ok_timeout = 0.01
        mom, sam = FakePeer(), FakePeer()
        mom_account, sam_account = account(store, "parent_mom"), account(store, "student_sam")
        await hub.join(mom_account, mom)
        await hub.join(sam_account, sam)
        await hub.message(sam_account, {"type": "sharing", "state": "on"})
        await hub.message(sam_account, {"type": "location", "lat": LAT, "lon": LON})
        rid = str(await hub.request_band(mom_account, "student_sam"))
        at = datetime.now(UTC).isoformat()
        secret = store.device_key("student_sam")[1]  # type: ignore[index]
        await hub.message(
            sam_account,
            {
                "type": "band_answer",
                "request_id": rid,
                "band": "nearby",
                "answered_at": at,
                "signature": signing.sign(secret, rid, "nearby", at),
            },
        )
        ok = str(await hub.ask_ok(mom_account, "student_sam"))
        await hub.message(sam_account, {"type": "ok_answer", "request_id": ok, "answer": "call_me"})
        await hub.message(sam_account, {"type": "arrived_home"})
        await asyncio.sleep(0.03)
        assert [m["state"] for m in mom.of("band_result")] == ["answered"]
        return [rid, ok]

    return asyncio.run(run())


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "demo.sqlite3")
    for a in ACCOUNTS:
        store.add_account(a)
    for parent, student, label in LINKS:
        store.link(parent, student, label)
    return store


def test_no_table_keeps_a_location_band_or_answer(store: Store, tmp_path: Path) -> None:
    ids = scenario(store)
    db = sqlite3.connect(tmp_path / "demo.sqlite3")
    tables = [r[0] for r in db.execute("select name from sqlite_master where type = 'table'")]
    columns = {(t, c[1]) for t in tables for c in db.execute(f"pragma table_info({t})")}
    location_like = {
        (t, c) for t, c in columns if c in {"lat", "lon", "latitude", "longitude", "location"}
    }
    assert location_like == WATCH_ZONE_COLUMNS
    assert not {
        (t, c) for t, c in columns if any(w in c for w in ("band", "answer", "request", "sharing"))
    }
    db.close()
    raw = (tmp_path / "demo.sqlite3").read_bytes()
    for needle in ("39.123457", "86.512345", "nearby", "call_me", *ids):
        assert needle.encode() not in raw, needle


def test_logs_name_no_one_and_nowhere(store: Store, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    ids = scenario(store)
    # States such as "answered" or "call_me" may appear; who, where and the band never do.
    for needle in ("39.12", "86.51", "nearby", "Sam", "student_sam", "Mom", *ids):
        assert needle not in caplog.text, needle
    assert "check-in request answered" in caplog.text and "arrived home sent" in caplog.text
