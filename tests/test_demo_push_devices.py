"""Phones register for push only after the push consent; tokens are never returned or logged."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings

TOKEN = "ExponentPushToken[abcdefghij0123456789]"  # noqa: S105 (made up)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    return TestClient(app)


def auth(client: TestClient, who: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": who}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def store(client: TestClient):  # type: ignore[no-untyped-def]
    return client.app.state.store  # type: ignore[attr-defined]


def test_register_needs_the_push_consent_and_a_real_token_shape(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    sam = auth(client, "student_sam")
    body = {"expo_token": TOKEN}
    assert client.post("/api/devices", headers=sam, json=body).status_code == 403
    client.post("/api/consents/push", headers=sam, json={"granted": True})
    assert (
        client.post("/api/devices", headers=sam, json={"expo_token": "nonsense"}).status_code == 400
    )
    made = client.post("/api/devices", headers=sam, json=body)
    assert made.status_code == 201 and TOKEN not in made.text
    assert store(client).devices_of("student_sam") == [TOKEN]
    assert TOKEN not in caplog.text


def test_at_most_five_phones_and_delete_removes_one(client: TestClient) -> None:
    sam = auth(client, "student_sam")
    client.post("/api/consents/push", headers=sam, json={"granted": True})
    tokens = [f"ExponentPushToken[phone{n}aaaaaaaaaa]" for n in range(6)]
    codes = [
        client.post("/api/devices", headers=sam, json={"expo_token": t}).status_code for t in tokens
    ]
    assert codes == [201] * 5 + [409]
    assert (
        client.request(
            "DELETE", "/api/devices", headers=sam, json={"expo_token": tokens[0]}
        ).status_code
        == 204
    )
    assert len(store(client).devices_of("student_sam")) == 4


def test_withdrawing_push_removes_every_phone(client: TestClient) -> None:
    mom = auth(client, "parent_mom")
    client.post("/api/consents/push", headers=mom, json={"granted": True})
    client.post("/api/devices", headers=mom, json={"expo_token": TOKEN})
    client.post("/api/consents/push", headers=mom, json={"granted": False})
    assert store(client).devices_of("parent_mom") == []


def test_a_phone_signed_into_another_account_moves_there(client: TestClient) -> None:
    for who in ("student_sam", "student_alex"):
        headers = auth(client, who)
        client.post("/api/consents/push", headers=headers, json={"granted": True})
        client.post("/api/devices", headers=headers, json={"expo_token": TOKEN})
    assert store(client).devices_of("student_sam") == []
    assert store(client).devices_of("student_alex") == [TOKEN]


def test_the_console_gets_no_push(client: TestClient) -> None:
    console = auth(client, "console")
    client.post("/api/consents/push", headers=console, json={"granted": True})
    assert (
        client.post("/api/devices", headers=console, json={"expo_token": TOKEN}).status_code == 403
    )
