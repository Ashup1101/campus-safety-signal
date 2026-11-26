"""Consents (Sprint 11): granted or withdrawn per feature, with the version and time, and gone
when the account is deleted. Made-up accounts."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
        )
    )


def auth(client: TestClient, who: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": who}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def states(client: TestClient, me: dict[str, str]) -> dict[str, Any]:
    return {c["kind"]: c for c in client.get("/api/consents", headers=me).json()}


def test_grant_withdraw_and_list_own_consents(client: TestClient) -> None:
    sam = auth(client, "student_sam")
    assert states(client, sam)["location_precise"]["state"] == "not_asked"
    granted = client.post("/api/consents/location_precise", headers=sam, json={"granted": True})
    assert granted.status_code == 200 and granted.json()["state"] == "granted"
    found = states(client, sam)["location_precise"]
    assert found["version"] and found["granted_at"] and found["withdrawn_at"] is None
    client.post("/api/consents/location_precise", headers=sam, json={"granted": False})
    assert states(client, sam)["location_precise"]["state"] == "withdrawn"
    client.post("/api/consents/notes", headers=sam, json={"granted": False})
    assert states(client, sam)["notes"]["state"] == "declined"
    assert states(client, auth(client, "student_alex"))["location_precise"]["state"] == "not_asked"
    assert (
        client.post("/api/consents/telepathy", headers=sam, json={"granted": True}).status_code
        == 404
    )


def test_deleting_the_account_removes_its_consents(client: TestClient) -> None:
    sam = auth(client, "student_sam")
    client.post("/api/consents/sharing", headers=sam, json={"granted": True})
    store = client.app.state.store  # type: ignore[attr-defined]
    account = store.account("student_sam")
    store.delete_account(account)
    assert store.consents("student_sam") == {}


# --- consent gates on the server ---

import asyncio  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from test_demo_server import FakePeer, hub_for  # noqa: E402

from demo_server import consents  # noqa: E402
from demo_server.store import Account, Store  # noqa: E402

KIM = Account("kim", "student", "Kim", True, "kim@example.test", self_service=True)
PAT = Account("pat", "parent", "Pat", True, "pat@example.test", self_service=True)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "demo.sqlite3")
    for account in (KIM, PAT):
        store.add_account(account)
    store.link("pat", "kim", "Mom")
    return store


def grant(store: Store, kind: str, yes: bool = True) -> None:
    store.set_consent("kim", kind, yes, consents.VERSION, datetime.now(UTC))


def test_sharing_needs_consent_and_withdrawing_stops_it(store: Store) -> None:
    async def run() -> tuple[str, str, FakePeer]:
        hub = hub_for(store)
        mom, kim = FakePeer(), FakePeer()
        await hub.join(PAT, mom)
        await hub.join(KIM, kim)
        await hub.message(KIM, {"type": "sharing", "state": "on"})
        before = hub.sharing("kim")
        grant(store, "sharing")
        await hub.message(KIM, {"type": "sharing", "state": "on"})
        grant(store, "sharing", yes=False)
        await hub.consent_withdrawn(KIM, "sharing")
        return before, hub.sharing("kim"), kim

    before, after, kim = asyncio.run(run())
    assert before == "off" and after == "off"
    assert kim.of("consent_needed")[0]["kind"] == "sharing"


def test_check_ins_need_precise_location_consent(store: Store) -> None:
    async def run() -> list[str]:
        hub = hub_for(store)
        mom, kim = FakePeer(), FakePeer()
        await hub.join(PAT, mom)
        await hub.join(KIM, kim)
        await hub.request_band(PAT, "kim")
        return [m["state"] for m in mom.of("band_result")] + [str(len(kim.of("band_request")))]

    assert asyncio.run(run()) == ["declined", "0"]  # the phone is never asked


def test_built_in_demo_personas_count_as_consented(tmp_path: Path) -> None:
    from demo_server.seed import ACCOUNTS

    persona = ACCOUNTS[0]
    assert consents.allowed(Store(tmp_path / "s.sqlite3"), persona, "sharing")
    assert not consents.allowed(Store(tmp_path / "t.sqlite3"), KIM, "sharing")


def test_digests_and_briefings_reach_only_people_who_opted_in(store: Store) -> None:
    assert consents.recipients(store, ["kim", "pat"], "digests") == []
    store.set_consent("pat", "digests", True, consents.VERSION, datetime.now(UTC))
    assert consents.recipients(store, ["kim", "pat"], "digests") == ["pat"]
