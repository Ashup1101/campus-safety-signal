"""Magic-link sign-in tokens: random, stored hashed, short-lived, single use."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from demo_target import store_at

from demo_server import auth
from demo_server.store import Account, Store

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(store_at(tmp_path))
    store.add_account(
        Account("p1", "parent", "Pat", False, email="pat@example.test", self_service=True)
    )
    return store


def test_a_token_signs_in_once_within_15_minutes(store: Store) -> None:
    token = auth.issue(store, "p1", NOW)
    assert len(token) >= 40 and token not in str(store.magic_rows())  # only the hash is stored
    assert auth.redeem(store, token, NOW + timedelta(minutes=14)) == "p1"
    assert auth.redeem(store, token, NOW + timedelta(minutes=14)) is None  # single use


def test_expired_unknown_or_tampered_tokens_change_nothing(store: Store) -> None:
    token = auth.issue(store, "p1", NOW)
    assert auth.redeem(store, token, NOW + timedelta(minutes=16)) is None
    assert auth.redeem(store, "not-a-token", NOW) is None
    assert auth.redeem(store, token[:-1] + ("A" if token[-1] != "A" else "B"), NOW) is None
    fresh = auth.issue(store, "p1", NOW)
    assert auth.redeem(store, fresh, NOW) == "p1"  # earlier failures left it untouched


def link_in_mailbox(store: Store, account_id: str) -> str:
    body = str(store.mailbox(account_id)[0]["body"])
    return body.split("/magic/")[1].split()[0]


def test_signup_sends_a_link_to_the_mailbox_and_never_returns_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from fastapi.testclient import TestClient

    from demo_server.app import create_app
    from demo_server.seed import Settings

    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    client = TestClient(app)
    store: Store = app.state.store
    body = {"email": " Pat@Example.test ", "role": "parent", "display_name": "Pat"}
    answer = client.post("/api/signup", json=body)
    assert answer.status_code == 202 and answer.json() == {"status": "sent"}
    account = store.account_by_email("pat@example.test")
    assert account is not None and account.self_service and not account.is_test
    assert store.mailbox(account.id)[0]["kind"] == "account"
    assert len(link_in_mailbox(store, account.id)) >= 40
    assert "pat@example.test" not in caplog.text.lower()
    assert client.post("/api/signup", json=body).status_code == 409  # one account per email
    for bad in (
        {**body, "email": "nope"},
        {**body, "display_name": " "},
        {**body, "role": "console"},
    ):
        assert client.post(
            "/api/signup", json={**bad, "email": bad.get("email", "x@y.test")}
        ).status_code in (400, 422)
    statuses = [
        client.post("/api/signin", json={"email": "pat@example.test"}).status_code for _ in range(6)
    ]
    assert statuses == [202, 202, 202, 202, 429, 429]  # 5 links per address per hour (incl. signup)
    assert (
        client.post("/api/signin", json={"email": "who@example.test"}).status_code == 202
    )  # no hint


def test_the_link_signs_in_once(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from demo_server.app import create_app
    from demo_server.seed import Settings

    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    client = TestClient(app)
    body = {"email": "sam@example.test", "role": "student", "display_name": "Sam"}
    client.post("/api/signup", json=body)
    account = app.state.store.account_by_email("sam@example.test")
    token = link_in_mailbox(app.state.store, account.id)
    session = client.get(f"/api/magic/{token}")
    assert session.status_code == 200
    assert session.json()["account"] == {"id": account.id, "role": "student", "name": "Sam"}
    me = {"Authorization": f"Bearer {session.json()['token']}"}
    assert client.get("/api/mailbox", headers=me).status_code == 200
    assert client.get(f"/api/magic/{token}").status_code == 400  # used
    assert client.get("/api/magic/nonsense").status_code == 400
