"""The OfficialAlertSource adapter: any official channel (web page poller, email inbox, CAP/RSS
feed, webhook, vendor API) yields OfficialAlerts, and the fan-out never needs to know which.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

SourceKind = Literal["web_page", "email", "cap_rss", "webhook", "vendor_api", "drill", "replay"]
Verification = Literal["official", "drill", "reconstruction"]


@dataclass(frozen=True)
class OfficialAlert:
    source: str
    kind: SourceKind
    text: str  # exactly as the source sent it (live official alerts are never edited)
    verification: Verification
    official_at: datetime | None  # when the source says it sent the alert
    status: str = "Severe"  # the source's own word, e.g. Severe / Normal
    external_id: str | None = None
    link: str | None = None

    @property
    def test_only(self) -> bool:
        """Drills and reconstructions reach test accounts only."""
        return self.verification != "official"


class OfficialAlertSource(Protocol):
    name: str
    kind: SourceKind

    def alerts(self) -> AsyncIterator[OfficialAlert]: ...


class QueueSource:
    """A source that something else pushes into (console drills, replays, webhooks)."""

    def __init__(self, name: str, kind: SourceKind) -> None:
        self.name = name
        self.kind: SourceKind = kind
        self._queue: asyncio.Queue[OfficialAlert] = asyncio.Queue()

    def push(self, alert: OfficialAlert) -> None:
        self._queue.put_nowait(alert)

    async def alerts(self) -> AsyncIterator[OfficialAlert]:
        while True:
            yield await self._queue.get()
