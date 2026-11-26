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
    # Check-in bands and answers are never stored. The survey table holds 1-5 numbers only.
    assert not {
        (t, c)
        for t, c in columns
        if t != "survey_answers" and any(w in c for w in ("band", "answer", "request", "sharing"))
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


def test_notes_leave_no_text_location_or_writer_in_logs_or_the_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient
    from test_demo_notes import KIRKWOOD_400, alert

    from demo_server import notes_api
    from demo_server.app import create_app
    from demo_server.seed import Settings

    monkeypatch.setattr(notes_api, "names_detector", lambda text: [])
    caplog.set_level(logging.DEBUG)
    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    client = TestClient(app)
    app.state.store.add_alert("a1", alert("Normal"), datetime.now(UTC), "t1")

    def auth(who: str) -> dict[str, str]:
        token = client.post("/api/login", json={"account_id": who}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    words = "Kirkwood closed near Dunn zebra"
    for who in ("student_sam", "student_alex"):
        body = {"tag": "Road closed", "text": words, **KIRKWOOD_400}
        assert client.post("/api/threads/t1/note", headers=auth(who), json=body).status_code == 201
    note_id = app.state.store.notes_of("t1")[0]["id"]
    client.post(f"/api/notes/{note_id}/report", headers=auth("parent_mom"))
    client.post(f"/api/console/notes/{note_id}/ban", headers=auth("console"))
    client.delete("/api/threads/t1/note", headers=auth("student_alex"))
    for needle in ("zebra", "39.166", "86.529", "student_sam", "student_alex", "Sam", "Alex"):
        assert needle not in caplog.text, needle
    db = sqlite3.connect(tmp_path / "d" / "demo.sqlite3")
    assert db.execute("select count(*) from notes").fetchone() == (0,)
    assert db.execute("select count(*) from note_reports").fetchone() == (0,)
    db.close()
    assert (
        b"zebra" not in (tmp_path / "d" / "demo.sqlite3").read_bytes()
    )  # wiped, not just unlinked
