"""Parent check-ins (v8): a linked parent asks, the phone answers with a signed band, the server
relays it and forgets. Made-up accounts; phones and parents are fake devices on the hub."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_demo_server import FakePeer, account, hub_for, store  # noqa: F401 (fixture)

from demo_server import signing
from demo_server.app import create_app
from demo_server.hub import Hub
from demo_server.seed import Settings
from demo_server.store import Store


def answer(secret: str, request_id: str, band: str) -> dict[str, str]:
    at = datetime.now(UTC).isoformat()
    return {
        "type": "band_answer",
        "request_id": request_id,
        "band": band,
        "answered_at": at,
        "signature": signing.sign(secret, request_id, band, at),
    }


async def joined(store: Store, hub: Hub) -> tuple[FakePeer, FakePeer]:  # noqa: F811
    mom, sam = FakePeer(), FakePeer()
    await hub.join(account(store, "parent_mom"), mom)
    await hub.join(account(store, "student_sam"), sam)
    return mom, sam


def test_a_signed_band_reaches_only_the_asking_parent(
    store: Store,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    secret = store.device_key("student_sam")[1]  # type: ignore[index]

    async def scenario() -> tuple[FakePeer, FakePeer, FakePeer, Hub]:
        hub = hub_for(store)
        mom, sam = await joined(store, hub)
        dad = FakePeer()
        await hub.join(account(store, "parent_dad"), dad)
        rid = await hub.request_band(account(store, "parent_mom"), "student_sam")
        assert rid is not None
        request = sam.of("band_request")[0]
        assert (request["from"], request["request_id"]) == ("Mom", rid)
        sam_account = account(store, "student_sam")
        await hub.message(sam_account, answer(secret, rid, "nearby"))
        await hub.message(sam_account, answer(secret, rid, "away"))  # request already answered
        return mom, sam, dad, hub

    mom, _, dad, hub = asyncio.run(scenario())
    [result] = mom.of("band_result")
    assert (result["state"], result["band"], result["student_id"]) == (
        "answered",
        "nearby",
        "student_sam",
    )
    assert dad.of("band_result") == []
    assert hub.pending_band_requests() == 0
    assert "nearby" not in caplog.text and "student_sam" not in caplog.text


def test_bad_signature_declined_and_unreachable(store: Store) -> None:  # noqa: F811
    async def scenario() -> list[dict[str, Any]]:
        hub = hub_for(store)
        hub.band_timeout = 0.01
        mom, _ = await joined(store, hub)
        sam = account(store, "student_sam")
        rid = await hub.request_band(account(store, "parent_mom"), "student_sam")
        await hub.message(sam, answer("00" * 32, str(rid), "inside"))  # not Sam's key
        rid = await hub.request_band(account(store, "parent_mom"), "student_sam")
        await hub.message(sam, {"type": "band_answer", "request_id": rid, "declined": True})
        await hub.request_band(account(store, "parent_mom"), "student_sam")  # phone stays silent
        await asyncio.sleep(0.05)
        return mom.of("band_result")

    results = asyncio.run(scenario())
    assert [r["state"] for r in results] == ["unverified", "declined", "unreachable"]
    assert all("band" not in r for r in results)


def test_an_offline_phone_is_unreachable(store: Store) -> None:  # noqa: F811
    async def scenario() -> FakePeer:
        hub = hub_for(store)
        mom = FakePeer()
        await hub.join(account(store, "parent_mom"), mom)
        await hub.request_band(account(store, "parent_mom"), "student_sam")
        return mom

    assert asyncio.run(scenario()).of("band_result")[0]["state"] == "unreachable"


def test_only_a_linked_parent_may_ask(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
        )
    )

    def ask(who: str) -> int:
        token = client.post("/api/login", json={"account_id": who}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        return client.post("/api/check-in/student_sam", headers=headers).status_code

    assert ask("parent_mom") == 202
    assert ask("parent_dad") == 403  # Dad is Alex's parent
    assert ask("student_alex") == 403


def test_are_you_ok_asks_the_student_first_and_tells_the_parent_only_without_an_answer(
    store: Store,  # noqa: F811
) -> None:
    async def scenario() -> tuple[FakePeer, FakePeer]:
        hub = hub_for(store)
        hub.ok_timeout = 0.02
        mom, sam = await joined(store, hub)
        mom_account, sam_account = account(store, "parent_mom"), account(store, "student_sam")
        first = await hub.ask_ok(mom_account, "student_sam")
        assert mom.of("ok_result") == []  # nothing for the parent until the student answers
        await hub.message(sam_account, {"type": "ok_answer", "request_id": first, "answer": "ok"})
        second = await hub.ask_ok(mom_account, "student_sam")
        await asyncio.sleep(0.05)  # ten minutes in the test clock: no answer yet
        await hub.message(
            sam_account, {"type": "ok_answer", "request_id": second, "answer": "call_me"}
        )
        third = await hub.ask_ok(mom_account, "student_sam")
        await hub.message(sam_account, {"type": "ok_answer", "request_id": third, "answer": "off"})
        await hub.message(sam_account, {"type": "ok_answer", "request_id": third, "answer": "ok"})
        assert hub.pending_ok_requests() == 0
        return mom, sam

    mom, sam = asyncio.run(scenario())
    assert [m["from"] for m in sam.of("ok_request")] == ["Mom", "Mom", "Mom"]
    assert [m["state"] for m in mom.of("ok_result")] == ["ok", "no_answer", "call_me", "off"]


def test_only_a_linked_parent_sends_are_you_ok(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
        )
    )

    def ask(who: str) -> int:
        token = client.post("/api/login", json={"account_id": who}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        return client.post("/api/are-you-ok/student_sam", headers=headers).status_code

    assert ask("parent_mom") == 202
    assert ask("parent_dad") == 403


def test_arrived_home_ends_sharing_once_on_an_event_night(store: Store) -> None:  # noqa: F811
    async def scenario(preset: str, sharing: str) -> FakePeer:
        hub = hub_for(store)
        hub.clock.set(preset)
        mom, _ = await joined(store, hub)
        sam = account(store, "student_sam")
        await hub.message(sam, {"type": "sharing", "state": sharing})
        await hub.message(sam, {"type": "arrived_home"})
        await hub.message(sam, {"type": "arrived_home"})  # once per night
        assert hub.sharing("student_sam") == ("off" if preset == "event_night" else sharing)
        return mom

    mom = asyncio.run(scenario("event_night", "on"))
    [arrived] = mom.of("arrived_home")
    assert arrived["student_id"] == "student_sam" and "lat" not in arrived
    assert mom.of("sharing")[-1]["state"] == "off"
    assert asyncio.run(scenario("late_night", "on")).of("arrived_home") == []  # not an event night
    assert asyncio.run(scenario("event_night", "off")).of("arrived_home") == []  # not sharing


def test_the_console_sees_outcome_counts_only(store: Store) -> None:  # noqa: F811
    async def scenario() -> dict[str, dict[str, int]]:
        hub = hub_for(store)
        mom = FakePeer()
        await hub.join(account(store, "parent_mom"), mom)
        await hub.request_band(account(store, "parent_mom"), "student_sam")  # phone offline
        hub.ok_timeout = 0.01
        await hub.ask_ok(account(store, "parent_mom"), "student_sam")
        await asyncio.sleep(0.03)
        return hub.reassurance_counts()

    assert asyncio.run(scenario()) == {
        "check_ins": {"unreachable": 1},
        "are_you_ok": {"no_answer": 1},
        "arrived_home": {"sent": 0},
    }


def test_reassurance_counts_are_console_only(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
        )
    )

    def get(who: str) -> Any:
        token = client.post("/api/login", json={"account_id": who}).json()["token"]
        return client.get("/api/console/reassurance", headers={"Authorization": f"Bearer {token}"})

    assert get("parent_mom").status_code == 403
    assert get("console").json()["check_ins"] == {}
