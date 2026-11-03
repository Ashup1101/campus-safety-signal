"""Official alert fast path: IU feed parsing and polling, descriptors, TLS. Made-up alerts."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from campus_safety import fetch
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.official import rave
from campus_safety.official.descriptors import MARKER, strip_descriptors

ROW = (
    '<tr><td tabindex="-1" data-label="Campus">{campus}</td>'
    '<td data-label="Status" tabindex="-1">{status}</td>'
    '<td data-label="Description" tabindex="-1">{text}</td>'
    '<td data-label="Created Date" tabindex="-1">{sent}</td></tr>'
)


def feed(*rows: tuple[str, str, str, str]) -> str:
    body = "".join(ROW.format(campus=c, status=s, text=t, sent=d) for c, s, t, d in rows)
    return (
        '<html><table class="rave-feed-results mobile-labels"><tbody><tr><th>Campus</th>'
        f"<th>Status</th><th>Description / Instruction</th><th>Date/Time Sent</th></tr>{body}"
        "</tbody></table></html>"
    )


OLD = ("IU Bloomington", "Severe", "IUB emergency: Test one &amp; two.", "Oct 3, 2026 9:05 PM")
NEW = ("IU Bloomington", "Severe", "IUB emergency: Avoid the test area.", "Oct 4, 2026 1:31 AM")
ELSEWHERE = ("IU East", "Severe", "IUE emergency: Not ours.", "Oct 4, 2026 1:32 AM")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Avoid it. Suspect described as tall. Call 911.", f"Avoid it. {MARKER} Call 911."),
        ("Suspect is a white male in his 20s. Avoid Grant St.", f"{MARKER} Avoid Grant St."),
        ("Last seen wearing a red jacket.", MARKER),
        ("Suspect is 5'10 with short hair. Shelter in place.", f"{MARKER} Shelter in place."),
        ("The suspect fled north in a white sedan.", "The suspect fled north in a white sedan."),
        ("Tornado warning. Seek shelter now.", "Tornado warning. Seek shelter now."),
    ],
)
def test_strip_descriptors(text: str, expected: str) -> None:
    assert strip_descriptors(text) == expected


def test_parse_feed_reads_every_row() -> None:
    alerts = rave.parse_feed(feed(OLD, ELSEWHERE))
    assert [a.campus for a in alerts] == ["IU Bloomington", "IU East"]
    assert alerts[0].text == "IUB emergency: Test one & two."
    assert alerts[0].sent_at.isoformat() == "2026-10-03T21:05:00-04:00"
    assert alerts[0].key != rave.parse_feed(feed(NEW))[0].key


@pytest.mark.parametrize(
    "html",
    [
        "<html><p>maintenance</p></html>",
        feed(OLD).replace('data-label="Status"', 'data-label="Level"'),
        feed(OLD).replace("Oct 3, 2026 9:05 PM", "yesterday"),
    ],
)
def test_parse_feed_refuses_a_changed_layout(html: str) -> None:
    with pytest.raises(rave.FeedLayoutError):
        rave.parse_feed(html)


class FakeFeed:
    def __init__(self) -> None:
        self.pages = [feed(OLD), feed(OLD), feed(NEW, ELSEWHERE, OLD)]
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> fetch.Page:
        self.calls.append(kwargs)
        if not self.pages:
            raise fetch.FetchError("down")
        body = self.pages.pop(0).encode()
        return fetch.Page(url, body, datetime(2026, 10, 4, 6, tzinfo=UTC), etag='"v1"')


def test_poller_relays_only_new_bloomington_alerts(tmp_path: Path) -> None:
    web = FakeFeed()
    lake = FileLake(tmp_path / "lake")
    source = rave.RaveFeedSource(lake=lake, get=web.get)
    assert asyncio.run(source.poll()) == []  # first poll: baseline only
    assert asyncio.run(source.poll()) == []  # unchanged
    relayed = asyncio.run(source.poll())
    assert [a.text for a in relayed] == ["IUB emergency: Avoid the test area."]
    alert = relayed[0]
    assert (alert.verification, alert.kind, alert.test_only) == ("official", "web_page", False)
    assert alert.official_at is not None and alert.official_at.hour == 1
    assert len(bronze.manifests(lake, rave.SOURCE)) == 2  # baseline + the page with news
    assert web.calls[1] == {"etag": '"v1"', "last_modified": None}


class Stop(Exception):
    pass


def test_poller_keeps_going_after_a_failure() -> None:
    web = FakeFeed()
    web.pages = []
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise Stop

    noon = datetime(2026, 3, 3, 17, tzinfo=UTC)
    source = rave.RaveFeedSource(get=web.get, sleep=sleep, now=lambda: noon)

    async def drain() -> None:
        async for _ in source.alerts():
            pass

    with pytest.raises(Stop):
        asyncio.run(drain())
    assert waits == [rave.INTERVAL_SECONDS, rave.INTERVAL_SECONDS]


def test_poller_polls_faster_late_at_night() -> None:
    late = datetime(2026, 3, 4, 4, 30, tzinfo=UTC)  # 23:30 in Bloomington
    assert rave.RaveFeedSource(now=lambda: late).interval() == rave.HIGH_ALERT_INTERVAL_SECONDS
