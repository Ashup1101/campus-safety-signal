"""The local mailbox channel: the demo's stand-in for email (no paid service, no domain).
Rendered messages land in the demo SQLite mailbox; nothing leaves the Mac. Message bodies are
never logged."""

import hashlib

from campus_safety.alerts.rules import Draft
from demo_server.store import Store

KINDS = {"briefing", "digest", "alert", "correction", "all_clear", "account"}


class MailboxChannel:
    name = "mailbox"

    def __init__(self, store: Store) -> None:
        self.store = store

    def deliver(
        self, account_id: str, draft: Draft, kind: str, key: str, thread_id: str | None = None
    ) -> bool:
        """True when the message was new for this key; False when it was already delivered."""
        if kind not in KINDS:
            raise ValueError(f"unknown mailbox kind: {kind}")
        return self.store.deliver_mail(key, account_id, kind, draft.title, draft.body, thread_id)

    def send(self, address: str, draft: Draft) -> str:
        """The alerts Channel protocol: an alert keyed by its content, so a resend is a no-op."""
        key = (
            "alert:" + hashlib.sha256(f"{address}|{draft.title}|{draft.body}".encode()).hexdigest()
        )
        self.deliver(address, draft, "alert", key)
        return key
