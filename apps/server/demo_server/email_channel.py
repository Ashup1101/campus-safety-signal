"""Real email (EMAIL_MODE=smtp) through any SMTP provider (Resend, Amazon SES, Supabase custom
SMTP...). Same deliver contract as the in-app mailbox, which keeps the reader's copy: one message
per key. Each email waits in the outbox until the provider accepts it, with up to MAX_ATTEMPTS
tries; failures keep only the error kind. Credentials and bodies are never logged."""

import logging
import os
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from campus_safety.alerts.rules import Draft
from demo_server.mailbox import MailboxChannel
from demo_server.store import Store

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
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

    def deliver(
        self, account_id: str, draft: Draft, kind: str, key: str, thread_id: str | None = None
    ) -> bool:
        fresh = super().deliver(account_id, draft, kind, key, thread_id)  # the in-app copy
        account = self.store.account(account_id)
        if fresh and account is not None and account.email:
            row = (key, account_id, kind, account.email, draft.title, draft.body, None)
            self.store.outbox_add(row, self._now())
            self.flush()
        return fresh

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
