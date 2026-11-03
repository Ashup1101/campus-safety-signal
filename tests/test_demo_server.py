"""Demo server guarantees: drill isolation, linked parents only, location never persisted, one
fan-out to every device. Made-up accounts, places, and alert texts."""

import asyncio
import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from campus_safety.official.alerts import OfficialAlert
from demo_server.app import create_app
from demo_server.hub import Clock, Hub
from demo_server.seed import ACCOUNTS, LINKS, Settings
from demo_server.sources import DrillSource, ReplaySource, load_replays
from demo_server.store import Account, Store

LAT, LON = 39.123457, -86.654321  # distinctive, so any stored copy would be found
REAL = Account("real_parent", "parent", "Real parent", False)
OFFICIAL = OfficialAlert(
    source="iu_rave_feed",
    kind="web_page",
    text="IUB emergency: Test alert. Suspect described as tall.",
    verification="official",
    official_at=datetime(2026, 10, 4, 5, 31, tzinfo=UTC),
)
REPLAYS = """
incidents:
  - id: test_night
    title: Test night
    occurred_at: 2026-10-04T01:00:00
    category: shooting
    segments: [kirkwood_400]
    summary: Made up.
    sources: [https://example.org/report]
    alerts:
      - sent_at: 2026-10-04T01:31:00
        status: Severe
        text: "Test alert. Suspect described as tall."
      - {sent_at: 2026-10-04T02:08:00, status: Normal, text: "Test final update."}
"""


class FakePeer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: Any, mode: str = "text") -> None:
        self.sent.append(data)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == kind]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "demo.sqlite3")
    for account in [*ACCOUNTS, REAL]:
        store.add_account(account)
    for parent, student, label in LINKS:
        store.link(parent, student, label)
    return store


def account(store: Store, account_id: str) -> Account:
    found = store.account(account_id)
    assert found is not None
    return found


def hub_for(store: Store) -> Hub:
    return Hub(store, Clock(), {"kirkwood_400": "E Kirkwood Ave, 400 block"})


def test_drills_and_replays_never_reach_real_accounts(store: Store) -> None:
    async def scenario() -> tuple[FakePeer, FakePeer]:
        hub = hub_for(store)
        mom, real = FakePeer(), FakePeer()
        await hub.join(account(store, "parent_mom"), mom)
        await hub.join(REAL, real)
        drills = DrillSource()
        drills.drill()
        drills.all_clear()
        stream = drills.alerts()
        for _ in range(2):
            await hub.publish(await anext(stream))
        await hub.publish(OFFICIAL)
        return mom, real

    mom, real = asyncio.run(scenario())
    assert [m["alert"]["text"][:5] for m in mom.of("alert")] == ["DRILL", "DRILL", "IUB e"]
    assert [m["alert"]["verification"] for m in real.of("alert")] == ["official"]
    assert store.alerts(include_test=False)[0]["verification"] == "official"


def test_one_fan_out_reaches_every_device_with_the_same_alert(store: Store) -> None:
    async def scenario() -> list[FakePeer]:
        hub = hub_for(store)
        peers = [FakePeer() for _ in range(4)]
        ids = ["student_sam", "student_sam", "parent_mom", "parent_dad"]
        for peer, account_id in zip(peers, ids, strict=True):
            await hub.join(account(store, account_id), peer)
        await hub.publish(OFFICIAL)
        return peers

    peers = asyncio.run(scenario())
    alerts = [p.of("alert") for p in peers]
    assert all(len(a) == 1 for a in alerts)
    assert len({a[0]["alert"]["id"] for a in alerts}) == 1
    assert alerts[0][0]["alert"]["text"] == OFFICIAL.text  # live relay is verbatim
    stored = store.alerts(include_test=True)[0]["text"]
    assert stored == "IUB emergency: Test alert. [description removed]"


def test_a_parent_never_sees_an_unlinked_student(store: Store) -> None:
    async def scenario() -> tuple[FakePeer, FakePeer, FakePeer]:
        hub = hub_for(store)
        sam, mom, dad = FakePeer(), FakePeer(), FakePeer()
        await hub.join(account(store, "student_sam"), sam)
        await hub.join(account(store, "parent_mom"), mom)
        await hub.join(account(store, "parent_dad"), dad)
        student = account(store, "student_sam")
        await hub.message(student, {"type": "sharing", "state": "on"})
        await hub.message(student, {"type": "location", "lat": LAT, "lon": LON})
        await hub.message(student, {"type": "heads_up", "segment_id": "kirkwood_400"})
        return sam, mom, dad

    sam, mom, dad = asyncio.run(scenario())
    assert [m["lat"] for m in mom.of("location")] == [LAT]
    assert mom.of("heads_up")[0]["segment_name"] == "E Kirkwood Ave, 400 block"
    assert [s["id"] for s in dad.of("hello")[0]["students"]] == ["student_alex"]
    assert not dad.of("location") and not dad.of("sharing") and not dad.of("heads_up")
    assert sam.of("viewers")[-1]["labels"] == ["Mom"]


def test_location_flows_only_while_sharing_and_a_parent_is_viewing(store: Store) -> None:
    async def scenario() -> tuple[FakePeer, FakePeer, Hub]:
        hub = hub_for(store)
        student = account(store, "student_sam")
        sam, mom = FakePeer(), FakePeer()
        await hub.join(student, sam)
        await hub.message(student, {"type": "sharing", "state": "on"})
        await hub.message(student, {"type": "location", "lat": LAT, "lon": LON})
        assert not hub.has_location("student_sam")  # nobody viewing: dropped
        await hub.join(account(store, "parent_mom"), mom)
        await hub.message(student, {"type": "location", "lat": LAT, "lon": LON})
        assert hub.has_location("student_sam")
        await hub.message(student, {"type": "sharing", "state": "paused"})
        await hub.message(student, {"type": "sharing", "state": "paused"})
        assert not hub.has_location("student_sam")
        await hub.message(student, {"type": "location", "lat": LAT, "lon": LON})
        await hub.message(student, {"type": "heads_up", "segment_id": "kirkwood_400"})
        await hub.message(student, {"type": "sharing", "state": "on"})
        await hub.message(student, {"type": "location", "lat": LAT, "lon": LON})
        await hub.leave(account(store, "parent_mom"), mom)
        assert not hub.has_location("student_sam")  # last viewer left: dropped
        return sam, mom, hub

    sam, mom, _ = asyncio.run(scenario())
    assert len(mom.of("location")) == 2
    assert mom.of("hello")[0]["students"][0]["sharing"] == "on"
    assert [m["state"] for m in mom.of("sharing")] == ["paused", "on"]  # one paused notice
    assert not mom.of("heads_up")  # paused: the parent is not told
    assert [m["labels"] for m in sam.of("viewers")] == [["Mom"], []]


def test_bad_location_values_are_ignored(store: Store) -> None:
    async def scenario() -> FakePeer:
        hub = hub_for(store)
        student, mom = account(store, "student_sam"), FakePeer()
        await hub.join(account(store, "parent_mom"), mom)
        await hub.message(student, {"type": "sharing", "state": "on"})
        for lat, lon in [(True, 1), ("39", -86), (91, 0), (float("nan"), 0)]:
            await hub.message(student, {"type": "location", "lat": lat, "lon": lon})
        return mom

    assert not asyncio.run(scenario()).of("location")


def test_replays_are_labeled_and_strip_descriptions(tmp_path: Path) -> None:
    path = tmp_path / "incidents.yaml"
    path.write_text(REPLAYS)
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async def scenario() -> list[OfficialAlert]:
        source = ReplaySource(load_replays(path), sleep=sleep)
        await source.play("test_night", speed=60)
        stream = source.alerts()
        return [await anext(stream) for _ in range(2)]

    alerts = asyncio.run(scenario())
    assert waits == [0.0, 37.0]
    assert alerts[0].text == (
        "RECONSTRUCTION (IU alert sent Oct 4, 2026, 1:31 AM): Test alert. [description removed]"
    )
    assert all(a.test_only and a.verification == "reconstruction" for a in alerts)
    assert alerts[1].official_at is not None
    assert alerts[1].official_at.isoformat() == "2026-10-04T02:08:00-04:00"  # IU's own time


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    manual = tmp_path / "incidents.yaml"
    manual.write_text(REPLAYS)
    settings = Settings(
        data_dir=tmp_path / "demo",
        warehouse=tmp_path / "missing.duckdb",
        manual=manual,
        tiles=tmp_path / "tiles",
        replay_speed=1e9,
    )
    return TestClient(create_app(settings))


def login(client: TestClient, account_id: str) -> str:
    response = client.post("/api/login", json={"account_id": account_id})
    assert response.status_code == 200
    token: str = response.json()["token"]
    return token


def test_api_flow_drill_acks_and_no_location_on_disk(
    client: TestClient, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with client:
        assert client.get("/api/alerts").status_code == 401
        assert client.post("/api/login", json={"account_id": "nobody"}).status_code == 404
        console, sam, mom = (login(client, a) for a in ("console", "student_sam", "parent_mom"))
        mine = {"Authorization": f"Bearer {mom}"}
        assert client.post("/api/drill", json={"action": "drill"}, headers=mine).status_code == 403
        segments = client.get("/api/segments", headers=mine).json()
        assert len(segments["features"]) == 13
        assert {"late_night", "event_night"} <= set(segments["features"][0]["properties"]["levels"])
        with (
            client.websocket_connect(f"/ws?token={sam}") as student,
            client.websocket_connect(f"/ws?token={mom}") as parent,
        ):
            assert student.receive_json()["type"] == "hello"
            assert parent.receive_json()["students"][0]["sharing"] == "off"
            assert student.receive_json() == {"type": "viewers", "labels": ["Mom"]}
            student.send_json({"type": "sharing", "state": "on"})
            assert parent.receive_json()["state"] == "on"
            student.send_text("not json")
            student.send_json({"type": "location", "lat": LAT, "lon": LON})
            assert parent.receive_json()["lat"] == LAT
            headers = {"Authorization": f"Bearer {console}"}
            client.post("/api/drill", json={"action": "drill"}, headers=headers)
            to_student, to_parent = student.receive_json(), parent.receive_json()
            assert to_student["alert"]["id"] == to_parent["alert"]["id"]
            assert to_student["alert"]["text"].startswith("DRILL:")
            alert_id = to_parent["alert"]["id"]
            parent.send_json({"type": "ack", "alert_id": alert_id, "client": "web"})
            student.send_json({"type": "ack", "alert_id": alert_id, "client": "ios"})
            student.send_json({"type": "sharing", "state": "off"})
            assert parent.receive_json()["state"] == "off"
            for _ in range(50):
                board = client.get("/api/latency", headers=headers).json()
                if board[0]["web_at"] and board[0]["ios_at"]:
                    break
                time.sleep(0.02)
            assert board[0]["web_at"] and board[0]["ios_at"]
    with sqlite3.connect(tmp_path / "demo" / "demo.sqlite3") as db:
        dump = "\n".join(db.iterdump())
    files = sorted(p.name for p in (tmp_path / "demo").iterdir())
    assert files == ["demo.sqlite3"]
    for value in (str(LAT), str(LON), "39.12345", "86.65432"):
        assert value not in dump
        assert value not in caplog.text


def test_console_replay_and_clock(client: TestClient) -> None:
    with client:
        console = login(client, "console")
        headers = {"Authorization": f"Bearer {console}"}
        replays = client.get("/api/replays", headers=headers).json()
        assert [r["id"] for r in replays] == ["test_night"]
        assert client.post("/api/replays/missing", headers=headers).status_code == 404
        clock = client.post("/api/clock", json={"preset": "event_night"}, headers=headers).json()
        assert clock["windows"] == ["late_night", "event_night"] and not clock["live"]
        assert client.post("/api/clock", json={"preset": "live"}, headers=headers).json()["live"]
        coverage = client.get("/api/coverage", headers=headers).json()
        assert "iu_log_2017_2024" in {g["gap_id"] for g in coverage["gaps"]}
