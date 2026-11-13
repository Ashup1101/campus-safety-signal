"""Delivery channels. Each sends one drafted alert to one subscriber address and returns a
provider id. Email goes through Resend (free under 100/day; SES later). Web Push and iPhone
push plug in behind the same Protocol in Phase 10.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Protocol

from campus_safety.alerts.rules import Draft
from campus_safety.fetch import USER_AGENT

log = logging.getLogger("alerts")
RESEND_URL = "https://api.resend.com/emails"
RESEND_KEY_VAR = "RESEND_API_KEY"
FROM_VAR = "ALERTS_FROM"  # e.g. alerts@<domain>; set in SSM/env, never in the repo
TIMEOUT_SECONDS = 15


class ChannelError(RuntimeError):
    pass


class Channel(Protocol):
    name: str

    def send(self, address: str, draft: Draft) -> str: ...


class LogChannel:
    """Development and tests: records what would have been sent, address and title only."""

    def __init__(self, name: str = "log") -> None:
        self.name = name
        self.sent: list[tuple[str, Draft]] = []

    def send(self, address: str, draft: Draft) -> str:
        self.sent.append((address, draft))
        return f"{self.name}-{len(self.sent)}"


class ResendEmail:
    name = "email"

    def __init__(self, key: str | None = None, sender: str | None = None) -> None:
        self.key = key or os.environ.get(RESEND_KEY_VAR, "")
        self.sender = sender or os.environ.get(FROM_VAR, "")
        if not self.key or not self.sender:
            raise ChannelError(f"{RESEND_KEY_VAR} and {FROM_VAR} must be set")

    def send(self, address: str, draft: Draft) -> str:
        body = {
            "from": self.sender,
            "to": [address],
            "subject": draft.title,
            "text": f"{draft.body}\n\nUnsubscribe: reply STOP or use the link in your settings.",
        }
        request = urllib.request.Request(
            RESEND_URL,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                answer = json.loads(response.read())
        except urllib.error.HTTPError as e:
            raise ChannelError(f"Resend returned HTTP {e.code}") from e
        except (OSError, json.JSONDecodeError) as e:
            raise ChannelError(f"Resend request failed: {type(e).__name__}") from e
        return str(answer.get("id", ""))
