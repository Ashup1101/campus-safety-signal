"""The local mailbox: the demo's stand-in for email. Made-up messages."""

import logging
from pathlib import Path

import pytest
from demo_target import store_at

from campus_safety.alerts.rules import Draft
from demo_server.mailbox import MailboxChannel
from demo_server.seed import ACCOUNTS
from demo_server.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    return store


def test_a_message_lands_once_per_key_newest_first(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    channel = MailboxChannel(store)
    first = channel.deliver(
        "parent_mom", Draft("Halloween weekend", "Made-up body"), "briefing", "b1"
    )
    assert first and not channel.deliver(
        "parent_mom", Draft("Halloween weekend", "Made-up body"), "briefing", "b1"
    )
    channel.deliver("parent_mom", Draft("Daily digest", "Two thefts"), "digest", "d1")
    mail = store.mailbox("parent_mom")
    assert [(m["kind"], m["subject"]) for m in mail] == [
        ("digest", "Daily digest"),
        ("briefing", "Halloween weekend"),
    ]
    assert store.mailbox("parent_dad") == []
    assert "Made-up body" not in caplog.text and "Two thefts" not in caplog.text


def test_the_channel_protocol_send_is_idempotent_on_content(store: Store) -> None:
    channel = MailboxChannel(store)
    first = channel.send("student_sam", Draft("Alert", "Text"))
    assert first == channel.send("student_sam", Draft("Alert", "Text"))
    assert len(store.mailbox("student_sam")) == 1


def test_unknown_kinds_are_refused(store: Store) -> None:
    with pytest.raises(ValueError, match="kind"):
        MailboxChannel(store).deliver("parent_mom", Draft("x", "y"), "sms", "k")
