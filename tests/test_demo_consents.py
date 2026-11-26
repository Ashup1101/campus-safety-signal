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
