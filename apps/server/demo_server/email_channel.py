"""Real email (EMAIL_MODE=smtp) through any SMTP provider (Resend, Amazon SES, Supabase custom
SMTP...). Same deliver contract as the in-app mailbox, which keeps the reader's copy: one message
per key. Each email waits in the outbox until the provider accepts it, with up to MAX_ATTEMPTS
tries; failures keep only the error kind. Credentials and bodies are never logged."""

import logging
import os
import re
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from campus_safety.alerts.rules import Draft
from demo_server import subscriptions
from demo_server.mailbox import MailboxChannel
from demo_server.store import Account, Store

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
UNSUBSCRIBE = re.compile(r"Stop these messages: (\S+)")
WITH_UNSUBSCRIBE = {"digest", "briefing"}
SUBSCRIPTION = {"digest": "digests", "briefing": "briefings"}
BEFORE_CONFIRMED = ("signin:", "confirm:")  # the only emails an unproven address may get
DAY = timedelta(days=1)
Sender = Callable[[EmailMessage], None]


@dataclass(frozen=True)
class EmailSettings:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = field(default="", repr=False)
    sender: str = ""  # "Campus Safety Signal <alerts@your-domain>"
    reply_to: str = ""
    daily_cap: int = 10

    @classmethod
    def from_env(cls) -> "EmailSettings":
        env = os.environ.get
        return cls(
            host=env("SMTP_HOST", ""),
            port=int(env("SMTP_PORT", "587") or 587),
            username=env("SMTP_USERNAME", ""),
            password=env("SMTP_PASSWORD", ""),
            sender=env("EMAIL_FROM", ""),
            reply_to=env("EMAIL_REPLY_TO", ""),
            daily_cap=int(env("EMAIL_DAILY_CAP", "10") or 10),
        )


def smtp_sender(settings: EmailSettings) -> Sender:
    """TLS always: implicit TLS on 465, STARTTLS otherwise."""

    def send(message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.port == 465:
            with smtplib.SMTP_SSL(settings.host, settings.port, context=context, timeout=20) as s:
                s.login(settings.username, settings.password)
                s.send_message(message)
            return
        with smtplib.SMTP(settings.host, settings.port, timeout=20) as s:
            s.starttls(context=context)
            s.login(settings.username, settings.password)
            s.send_message(message)

    return send


class EmailChannel(MailboxChannel):
    name = "email"

    def __init__(
        self,
        store: Store,
        settings: EmailSettings,
        sender: Sender | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(store)
        self.settings = settings
        self._send = sender or smtp_sender(settings)
        self._now = now
        self.skipped: dict[str, int] = {}

    def deliver(
        self, account_id: str, draft: Draft, kind: str, key: str, thread_id: str | None = None
    ) -> bool:
        fresh = super().deliver(account_id, draft, kind, key, thread_id)  # the in-app copy
        account = self.store.account(account_id)
        if fresh and account is not None and account.email and self._may_send(account, kind, key):
            found = UNSUBSCRIBE.search(draft.body) if kind in WITH_UNSUBSCRIBE else None
            stop = found.group(1) if found else None
            row = (key, account_id, kind, account.email, draft.title, draft.body, stop)
            self.store.outbox_add(row, self._now())
            self.flush()
        return fresh

    def _may_send(self, account: Account, kind: str, key: str) -> bool:
        """Sending rules; a skipped email still has its in-app copy. Logs the rule, never who."""
        rule = None
        if not key.startswith(BEFORE_CONFIRMED) and not self.store.email_confirmed(account.id):
            rule = "unconfirmed_address"
        elif kind in SUBSCRIPTION and not subscriptions.active(
            self.store, account, SUBSCRIPTION[kind]
        ):
            rule = "unsubscribed"
        elif self.store.outbox_to_since(str(account.email), self._now() - DAY) >= (
            self.settings.daily_cap
        ):
            rule = "daily_cap"
        if rule:
            self.skipped[rule] = self.skipped.get(rule, 0) + 1
            log.info("email skipped: %s", rule)
        return rule is None

    def message(self, row: dict[str, object]) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = str(row["to_address"])
        message["Subject"] = str(row["subject"])
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(
            domain=self.settings.sender.rpartition("@")[2].strip(">") or None
        )
        if self.settings.reply_to:
            message["Reply-To"] = self.settings.reply_to
        if row.get("unsubscribe_url"):  # one-click unsubscribe (RFC 8058) for digests and briefings
            message["List-Unsubscribe"] = f"<{row['unsubscribe_url']}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        message.set_content(str(row["body"]))
        return message

    def flush(self) -> dict[str, int]:
        """Try every queued email once; counts by result (kinds only in logs)."""
        result = {"sent": 0, "failed": 0}
        for row in self.store.outbox_due(MAX_ATTEMPTS):
            try:
                self._send(self.message(row))
            except Exception as exc:  # the provider refused or the network failed: retry later
                self.store.outbox_failed(str(row["key"]), type(exc).__name__, MAX_ATTEMPTS)
                log.warning(
                    "email not sent (%s, try %d)", type(exc).__name__, int(row["attempts"]) + 1
                )
                result["failed"] += 1
            else:
                self.store.outbox_sent(str(row["key"]), self._now())
                result["sent"] += 1
        return result
