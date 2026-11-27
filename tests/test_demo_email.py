"""EMAIL_MODE=smtp with a fake provider: nothing leaves the Mac in tests."""

import logging
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest
from demo_target import store_at

from campus_safety.alerts.rules import Draft
from demo_server.email_channel import MAX_ATTEMPTS, EmailChannel, EmailSettings
from demo_server.store import Account, Store

NOW = datetime(2026, 11, 27, 8, tzinfo=UTC)
SETTINGS = EmailSettings(
    host="smtp.example.test", sender="Campus Safety Signal <alerts@example.test>"
)
PAT = Account("parent_pat", "parent", "Pat", False, "pat@example.test", True)
KIM = Account("student_kim", "student", "Kim", False, "kim@example.test", True)


def plain(message: EmailMessage) -> str:
    part = message.get_body(("plain",))
    assert part is not None
    return str(part.get_content())


class FakeProvider:
    def __init__(self, failures: int = 0) -> None:
        self.sent: list[EmailMessage] = []
        self.failures = failures

    def __call__(self, message: EmailMessage) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("provider down")
        self.sent.append(message)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(store_at(tmp_path))
    store.add_account(PAT)
    store.set_auth_user(PAT.id, "user-pat")  # signed in once: a confirmed address
    store.add_account(KIM)  # never signed in: unconfirmed
    return store


def channel(store: Store, provider: FakeProvider) -> EmailChannel:
    return EmailChannel(store, SETTINGS, provider, now=lambda: NOW)


def test_one_email_per_key_and_the_mailbox_keeps_a_copy(store: Store) -> None:
    provider = FakeProvider()
    email = channel(store, provider)
    assert email.deliver(PAT.id, Draft("Hello", "Body text"), "account", "k1") is True
    assert email.deliver(PAT.id, Draft("Hello", "Body text"), "account", "k1") is False
    assert len(provider.sent) == 1 and len(store.mailbox(PAT.id)) == 1
    message = provider.sent[0]
    assert message["To"] == "pat@example.test" and message["Subject"] == "Hello"
    assert message["From"] == SETTINGS.sender and "Body text" in plain(message)
    assert store.outbox_counts() == {"sent": 1}


def test_failures_retry_up_to_three_times_then_stop(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    provider = FakeProvider(failures=10)
    email = channel(store, provider)
    email.deliver(PAT.id, Draft("Hello", "secret-ish body"), "account", "k1")
    for _ in range(5):
        email.flush()
    assert provider.sent == [] and store.outbox_counts() == {"failed": 1}
    assert caplog.text.count("ConnectionError") == MAX_ATTEMPTS
    assert "secret-ish body" not in caplog.text and "pat@example.test" not in caplog.text


def test_a_later_flush_sends_what_failed_before(store: Store) -> None:
    provider = FakeProvider(failures=1)
    email = channel(store, provider)
    email.deliver(PAT.id, Draft("Hello", "Body"), "account", "k1")
    assert store.outbox_counts() == {"queued": 1}
    assert email.flush() == {"sent": 1, "failed": 0}
    assert len(provider.sent) == 1


def test_sent_bodies_are_cleared_and_delete_account_removes_the_outbox(store: Store) -> None:
    email = channel(store, FakeProvider())
    email.deliver(PAT.id, Draft("Hello", "Body"), "account", "k1")
    assert store.outbox_due(MAX_ATTEMPTS) == []
    store.delete_account(PAT)
    assert store.outbox_counts() == {}


def test_the_password_is_not_in_the_settings_repr() -> None:
    settings = EmailSettings(password="pw-for-test-only")  # noqa: S106
    assert "pw-for-test-only" not in repr(settings)


def test_unconfirmed_addresses_get_only_sign_in_and_confirm_emails(store: Store) -> None:
    provider = FakeProvider()
    email = channel(store, provider)
    email.deliver(KIM.id, Draft("Notice", "b"), "account", "unlink:1")
    email.deliver(KIM.id, Draft("Your sign-in link", "b"), "account", "signin:kim:1")
    email.deliver(KIM.id, Draft("Confirm your digests", "b"), "account", "confirm:digests:kim:1")
    assert [m["Subject"] for m in provider.sent] == ["Your sign-in link", "Confirm your digests"]
    assert email.skipped == {"unconfirmed_address": 1}
    assert len(store.mailbox(KIM.id)) == 3  # the app still shows all three
    store.set_subscription(KIM.id, "digests", "active")  # the confirm link was used
    email.deliver(KIM.id, Draft("Notice", "b"), "account", "unlink:2")
    assert provider.sent[-1]["Subject"] == "Notice"


def test_unsubscribed_kinds_are_never_emailed(store: Store) -> None:
    provider = FakeProvider()
    email = channel(store, provider)
    store.set_subscription(PAT.id, "digests", "active")
    store.set_subscription(PAT.id, "briefings", "unsubscribed")
    email.deliver(PAT.id, Draft("Briefing", "b"), "briefing", "b1")
    email.deliver(PAT.id, Draft("Digest", "b"), "digest", "d1")
    assert [m["Subject"] for m in provider.sent] == ["Digest"]
    assert email.skipped == {"unsubscribed": 1}


def test_a_daily_cap_per_address(store: Store, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    provider = FakeProvider()
    email = EmailChannel(store, EmailSettings(daily_cap=2), provider, now=lambda: NOW)
    for n in range(4):
        email.deliver(PAT.id, Draft("Link", "b"), "account", f"signin:pat:{n}")
    assert len(provider.sent) == 2 and email.skipped == {"daily_cap": 2}
    assert "pat@example.test" not in caplog.text
