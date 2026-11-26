"""Double opt-in and one-click unsubscribe for briefings and digests. Made-up accounts."""

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from demo_server import consents, subscriptions
from demo_server.app import create_app
from demo_server.seed import Settings
from demo_server.store import Account

PAT = Account("pat", "parent", "Pat", True, "pat@example.test", self_service=True)


def setup(tmp_path: Path) -> tuple[object, TestClient]:
    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    app.state.store.add_account(PAT)
    return app, TestClient(app)


def link(text: str, purpose: str) -> str:
    found = re.search(rf"/api/subscriptions/{purpose}/([A-Za-z0-9_-]+)", text)
    assert found, purpose
    return found.group(1)


def test_opting_in_sends_a_confirm_link_and_nothing_else_until_confirmed(tmp_path: Path) -> None:
    app, client = setup(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    store.set_consent("pat", "digests", True, consents.VERSION, datetime.now(UTC))
    subscriptions.start(store, PAT, "digests", base="http://test")
    assert subscriptions.recipients(store, ["pat"], "digests") == []  # pending confirmation
    [confirm] = [m for m in store.mailbox("pat") if m["kind"] == "account"]
    token = link(confirm["body"], "confirm")
    assert client.get(f"/api/subscriptions/unsubscribe/{token}").status_code == 404  # one purpose
    assert client.get(f"/api/subscriptions/confirm/{token}").json() == {"state": "active"}
    assert subscriptions.recipients(store, ["pat"], "digests") == ["pat"]


def test_every_message_carries_an_unsubscribe_link_that_works(tmp_path: Path) -> None:
    app, client = setup(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    store.set_consent("pat", "briefings", True, consents.VERSION, datetime.now(UTC))
    subscriptions.start(store, PAT, "briefings", base="http://test")
    store.set_subscription("pat", "briefings", "active")
    body = subscriptions.with_unsubscribe(
        store, "pat", "briefings", "Busy night ahead.", base="http://test"
    )
    token = link(body, "unsubscribe")
    assert client.get(f"/api/subscriptions/unsubscribe/{token}").json() == {"state": "unsubscribed"}
    assert subscriptions.recipients(store, ["pat"], "briefings") == []
    assert client.get("/api/subscriptions/unsubscribe/nope").status_code == 404
