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
