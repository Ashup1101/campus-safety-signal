"""Check-ins: linked family only, live threads only, memory only. Made-up accounts and alerts."""

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from demo_target import store_at

from campus_safety.official.alerts import OfficialAlert
from demo_server.hub import Clock, Hub
from demo_server.seed import ACCOUNTS, LINKS
from demo_server.store import Account, Store


def official(status: str = "Severe") -> OfficialAlert:
    return OfficialAlert(
        source="feed",
        kind="web_page",
        text="Made-up alert.",
        verification="official",
        official_at=datetime(2026, 10, 4, 5, 0, tzinfo=UTC),
        status=status,
    )


class Peer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: Any, mode: str = "text") -> None:
        self.sent.append(data)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == kind]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    for parent, student, label in LINKS:
        store.link(parent, student, label)
    return store


def acc(store: Store, account_id: str) -> Account:
    found = store.account(account_id)
    assert found is not None
    return found


def test_check_in_reaches_linked_parents_only(store: Store) -> None:
    async def scenario() -> tuple[Peer, Peer, Peer]:
        hub, sam, mom, dad = Hub(store, Clock(), {}), Peer(), Peer(), Peer()
        await hub.join(acc(store, "student_sam"), sam)
        await hub.join(acc(store, "parent_mom"), mom)
        await hub.join(acc(store, "parent_dad"), dad)
        thread = (await hub.publish(official()))["thread_id"]
        student = acc(store, "student_sam")
        await hub.message(student, {"type": "check_in", "thread_id": thread, "state": "safe"})
        return sam, mom, dad

    sam, mom, dad = asyncio.run(scenario())
    check_in = mom.of("check_in")[0]["check_in"]
    assert (check_in["student_id"], check_in["state"], check_in["place"]) == (
        "student_sam",
        "safe",
        None,
    )
    assert sam.of("check_in")  # the student's own devices see what was sent
    assert not dad.of("check_in")  # Dad is linked to Alex, not Sam


@pytest.mark.parametrize(
    "message",
    [
        {"type": "check_in", "thread_id": "no-such-thread", "state": "safe"},
        {"type": "check_in", "state": "safe"},
        {"type": "check_in", "thread_id": None, "state": "fine"},
        {"type": "check_in", "thread_id": None, "state": "sheltering"},
        {"type": "check_in", "thread_id": None, "state": "sheltering", "place": "Room 214"},
    ],
)
def test_invalid_check_ins_are_ignored(store: Store, message: dict[str, Any]) -> None:
    async def scenario() -> Peer:
        hub, mom = Hub(store, Clock(), {}), Peer()
        await hub.join(acc(store, "parent_mom"), mom)
        thread = (await hub.publish(official()))["thread_id"]
        if message.get("thread_id", "") is None:
            message["thread_id"] = thread
        await hub.message(acc(store, "student_sam"), message)
        return mom

    assert not asyncio.run(scenario()).of("check_in")


def test_a_newer_check_in_replaces_the_older_and_the_all_clear_forgets_it(
    store: Store, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    caplog.set_level(logging.DEBUG)

    async def scenario() -> tuple[Peer, Peer, Peer, Hub]:
        hub, sam, mom = Hub(store, Clock(), {}), Peer(), Peer()
        student = acc(store, "student_sam")
        await hub.join(student, sam)
        await hub.join(acc(store, "parent_mom"), mom)
        thread = (await hub.publish(official()))["thread_id"]
        await hub.message(student, {"type": "check_in", "thread_id": thread, "state": "safe"})
        await hub.message(
            student,
            {
                "type": "check_in",
                "thread_id": thread,
                "state": "sheltering",
                "place": "the library",
            },
        )
        assert [c["state"] for c in hub.check_ins(thread)] == ["sheltering"]
        late = Peer()  # a parent screen opened mid-alert sees the current check-in
        await hub.join(acc(store, "parent_mom"), late)
        await hub.publish(official("Normal"))
        assert hub.check_ins(thread) == []
        await hub.message(student, {"type": "check_in", "thread_id": thread, "state": "safe"})
        return sam, mom, late, hub

    sam, mom, late, _ = asyncio.run(scenario())
    assert [m["check_in"]["place"] for m in mom.of("check_in")] == [None, "the library"]
    assert [c["place"] for c in late.of("hello")[0]["check_ins"]] == ["the library"]
    assert len(mom.of("check_in_cleared")) == 1 and len(sam.of("check_in_cleared")) == 1
    with sqlite3.connect(tmp_path / "demo.sqlite3") as db:
        dump = "\n".join(db.iterdump())
    for value in ("sheltering", "the library"):
        assert value not in dump
        assert value not in caplog.text


def test_console_sees_check_in_counts_never_content(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from demo_server.app import create_app
    from demo_server.seed import Settings

    settings = Settings(
        data_dir=tmp_path / "demo",
        warehouse=tmp_path / "missing.duckdb",
        manual=tmp_path / "missing.yaml",
        tiles=tmp_path / "tiles",
    )
    client = TestClient(create_app(settings))
    with client:
        tokens = {
            a: client.post("/api/login", json={"account_id": a}).json()["token"]
            for a in ("console", "student_sam")
        }
        console = {"Authorization": f"Bearer {tokens['console']}"}
        with client.websocket_connect(f"/ws?token={tokens['student_sam']}") as sam:
            sam.receive_json()
            client.post("/api/drill", json={"action": "drill"}, headers=console)
            thread = sam.receive_json()["alert"]["thread_id"]
            sam.send_json(
                {"type": "check_in", "thread_id": thread, "state": "sheltering", "place": "my room"}
            )
            assert sam.receive_json()["type"] == "check_in"
            board = client.get("/api/latency", headers=console).json()
    assert board[0]["thread_id"] == thread and board[0]["check_ins"] == 1
    assert "my room" not in str(board) and "sheltering" not in str(board)
