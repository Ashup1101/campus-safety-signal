"""EMAIL_MODE picks the channel: mailbox (default) or real email too (smtp; a fake provider)."""

from datetime import UTC, date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from demo_target import store_at
from fastapi.testclient import TestClient

from campus_safety.events import Event
from demo_server import email_channel
from demo_server.app import create_app
from demo_server.email_channel import EmailChannel, EmailSettings
from demo_server.scheduler import Scheduler
from demo_server.seed import Settings
from demo_server.store import Account, Store

SENT: list[EmailMessage] = []


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    SENT.clear()
    monkeypatch.setattr(email_channel, "smtp_sender", lambda settings: SENT.append)
    monkeypatch.setenv("EMAIL_FROM", "Campus Safety Signal <alerts@example.test>")


def client_for(tmp_path: Path, mode: str) -> tuple[Any, TestClient]:
    settings = Settings(
        data_dir=tmp_path / "d",
        warehouse=tmp_path / "n.duckdb",
        tiles=tmp_path / "t",
        email_mode=mode,
    )
    app = create_app(settings)
    return app, TestClient(app)


def sign_up(client: TestClient, email: str, role: str) -> dict[str, str]:
    from test_demo_auth import link_in_mailbox

    client.post("/api/signup", json={"email": email, "role": role, "display_name": "Pat"})
    store = client.app.state.store  # type: ignore[attr-defined]
    token = link_in_mailbox(store, store.account_by_email(email).id)
    return {"Authorization": f"Bearer {client.get(f'/api/magic/{token}').json()['token']}"}


def subjects() -> list[str]:
    return [str(m["Subject"]) for m in SENT]


def test_smtp_mode_emails_sign_in_confirm_and_account_notices(tmp_path: Path) -> None:
    app, client = client_for(tmp_path, "smtp")
    pat = sign_up(client, "pat@example.test", "parent")
    assert subjects() == ["Your sign-in link"]
    assert "/magic/" in SENT[0].get_content() and SENT[0]["To"] == "pat@example.test"
    client.post("/api/consents/digests", headers=pat, json={"granted": True})
    assert subjects()[-1] == "Confirm your morning digests"
    kim = sign_up(client, "kim@example.test", "student")
    invite = client.post("/api/invites", headers=pat, json={"student_email": "kim@example.test"})
    client.post(f"/api/invites/{invite.json()['id']}/accept", headers=kim)
    kim_id = app.state.store.account_by_email("kim@example.test").id
    client.delete(f"/api/links/{kim_id}", headers=pat)
    assert subjects()[-1] == "Pat unlinked" and SENT[-1]["To"] == "kim@example.test"
    assert len(app.state.store.mailbox(kim_id)) >= 2  # the in-app copy is kept


def test_mailbox_mode_sends_no_email(tmp_path: Path) -> None:
    app, client = client_for(tmp_path, "mailbox")
    sign_up(client, "pat@example.test", "parent")
    assert SENT == []
    pat_id = app.state.store.account_by_email("pat@example.test").id
    assert app.state.store.mailbox(pat_id)[0]["subject"] == "Your sign-in link"


def test_briefings_and_digests_go_by_email_with_their_unsubscribe_link(tmp_path: Path) -> None:
    store = Store(store_at(tmp_path))
    pat = Account("parent_pat", "parent", "Pat", False, "pat@example.test", True)
    store.add_account(pat)
    now = datetime(2026, 10, 29, 15, 5)  # local wall time, as the scheduler reads it
    for kind in ("briefings", "digests"):
        store.set_consent(pat.id, kind, True, "v", datetime.now(UTC))
        store.set_subscription(pat.id, kind, "active")
    channel = EmailChannel(store, EmailSettings(sender="a@example.test"), SENT.append)
    halloween = Event("h", "Halloween weekend", (date(2026, 10, 30), date(2026, 10, 31)), "x")
    found = Scheduler(store, channel, tmp_path / "none.duckdb", {}, [halloween], lambda: now)
    found.tick()
    assert subjects() == ["Before Halloween weekend (Fri Oct 30 and Sat Oct 31)"]
    assert "Stop these messages: " in SENT[0].get_content()
    from campus_safety.alerts.rules import Draft

    channel.deliver(pat.id, Draft("Your morning digest", "Nothing new."), "digest", "d1")
    assert subjects()[-1] == "Your morning digest"


def test_digest_and_briefing_emails_carry_one_click_unsubscribe(tmp_path: Path) -> None:
    from campus_safety.alerts.rules import Draft
    from demo_server import subscriptions

    app, client = client_for(tmp_path, "smtp")
    store = app.state.store
    pat = Account("parent_pat", "parent", "Pat", False, "pat@example.test", True)
    store.add_account(pat)
    store.set_subscription(pat.id, "digests", "active")
    body = subscriptions.with_unsubscribe(store, pat.id, "digests", "Nothing new.", "http://x.test")
    app.state.scheduler_channel.deliver(pat.id, Draft("Your digest", body), "digest", "d1")
    app.state.scheduler_channel.deliver(pat.id, Draft("Notice", "No link."), "account", "a1")
    digest, notice = SENT[-2], SENT[-1]
    url = digest["List-Unsubscribe"].strip("<>")
    assert url.startswith("http://x.test/api/subscriptions/unsubscribe/")
    assert digest["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert notice["List-Unsubscribe"] is None
    token = url.rsplit("/", 1)[1]
    assert client.post(f"/api/subscriptions/unsubscribe/{token}").json() == {
        "state": "unsubscribed"
    }
    assert store.subscription(pat.id, "digests") == "unsubscribed"
    assert client.post("/api/subscriptions/unsubscribe/not-a-token").status_code == 404
