"""IU's public alert feed (emergency.iu.edu/rave): every IU Notify alert with campus, status,
text, and time sent. The first real OfficialAlertSource.

Polled every 60 s (30 s in high-alert windows) with an honest User-Agent after a robots.txt check,
conditional headers when the server offers them, and dedupe on (campus, time sent, text hash). The
first poll only records what is already there; later polls relay new alerts verbatim. Changed
pages are kept in bronze. Logs carry counts only.
"""

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

from campus_safety import events, fetch
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake
from campus_safety.official.alerts import OfficialAlert, SourceKind

URL = "https://emergency.iu.edu/rave/index.html"
SOURCE = "iu_rave_feed"
BLOOMINGTON = "IU Bloomington"
INTERVAL_SECONDS = 60.0
HIGH_ALERT_INTERVAL_SECONDS = 30.0
_COLUMNS = ("Campus", "Status", "Description", "Created Date")
_SENT = "%b %d, %Y %I:%M %p"

log = logging.getLogger(__name__)


class FeedLayoutError(ValueError):
    """The page no longer has the table we know; never guess at a changed layout."""


@dataclass(frozen=True)
class RaveAlert:
    campus: str
    status: str
    text: str
    sent_at: datetime  # aware, minute precision as published

    @property
    def key(self) -> tuple[str, datetime, str]:
        return self.campus, self.sent_at, hashlib.sha256(self.text.encode()).hexdigest()[:16]


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._row: dict[str, str] | None = None
        self._cell: str | None = None
        self._text: list[str] = []
        self.in_feed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "table" and "rave-feed-results" in (found.get("class") or ""):
            self.in_feed = True
        elif self.in_feed and tag == "tr":
            self._row = {}
        elif self._row is not None and tag == "td":
            self._cell, self._text = found.get("data-label") or "", []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row[self._cell] = " ".join("".join(self._text).split())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table" and self.in_feed:
            self.in_feed = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._text.append(data)


def parse_feed(html: str) -> list[RaveAlert]:
    table = _Table()
    table.feed(html)
    alerts = []
    for index, row in enumerate(table.rows):
        if tuple(row) != _COLUMNS:
            raise FeedLayoutError(f"row {index}: columns {sorted(row)}")
        try:
            sent = datetime.strptime(row["Created Date"], _SENT)
        except ValueError as e:
            raise FeedLayoutError(f"row {index}: unreadable Created Date") from e
        alerts.append(
            RaveAlert(
                campus=row["Campus"],
                status=row["Status"],
                text=row["Description"],
                sent_at=sent.replace(tzinfo=events.LOCAL),
            )
        )
    if not alerts:
        raise FeedLayoutError("no alert rows")
    return alerts


Get = Callable[..., fetch.Page]


class RaveFeedSource:
    name = SOURCE
    kind: SourceKind = "web_page"

    def __init__(
        self,
        campus: str = BLOOMINGTON,
        lake: Lake | None = None,
        get: Get | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.campus = campus
        self._lake = lake
        self._get = get
        self._sleep = sleep
        self._now = now
        self._seen: set[tuple[str, datetime, str]] | None = None
        self._etag: str | None = None
        self._last_modified: str | None = None

    def interval(self) -> float:
        high = events.high_alert(self._now())
        return HIGH_ALERT_INTERVAL_SECONDS if high else INTERVAL_SECONDS

    async def poll(self) -> list[OfficialAlert]:
        """One poll: new alerts for this campus, oldest first (none on the first poll)."""
        get = self._get or fetch.polite_get
        page = await asyncio.to_thread(get, URL, etag=self._etag, last_modified=self._last_modified)
        self._etag, self._last_modified = page.etag, page.last_modified
        if page.status == 304:
            return []
        found = parse_feed(page.body.decode("utf-8", errors="replace"))
        first = self._seen is None
        seen = self._seen if self._seen is not None else set()
        new = [alert for alert in found if alert.key not in seen]
        seen.update(alert.key for alert in found)
        self._seen = seen
        if new and self._lake is not None:
            bronze.write(
                self._lake,
                source=SOURCE,
                body=page.body,
                url=URL,
                fetched_at=page.fetched_at,
                http_status=page.status,
                run_id=bronze.new_run_id(),
                ext="html",
            )
        if first:
            return []
        relay = sorted((a for a in new if a.campus == self.campus), key=lambda a: a.sent_at)
        return [
            OfficialAlert(
                source=SOURCE,
                kind=self.kind,
                text=alert.text,
                verification="official",
                official_at=alert.sent_at,
                status=alert.status,
                external_id=alert.key[2],
                link=URL,
            )
            for alert in relay
        ]

    async def alerts(self) -> AsyncIterator[OfficialAlert]:
        while True:
            try:
                for alert in await self.poll():
                    yield alert
            except (fetch.FetchError, FeedLayoutError) as e:
                log.warning("%s poll failed: %s", SOURCE, type(e).__name__)
            await self._sleep(self.interval())
