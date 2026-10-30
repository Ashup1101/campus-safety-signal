"""Phase 2a collectors with a fake network. All content is made up."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from campus_safety import fetch
from campus_safety.collectors import cli
from campus_safety.collectors.poll import poll
from campus_safety.collectors.sources import BY_NAME, SOURCES
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake

FEED = b"<rss><channel><item><title>a</title></item><item><title>b</title></item></channel></rss>"


class FakeWeb:
    def __init__(self) -> None:
        self.bodies: dict[str, bytes] = {s.url: b"<html>notice</html>" for s in SOURCES}
        self.bodies[BY_NAME["news_ipm"].url] = FEED
        self.down: set[str] = set()
        self.clock = datetime(2026, 10, 30, tzinfo=UTC)

    def get(self, url: str, **kwargs: object) -> fetch.Page:
        if url in self.down:
            raise fetch.HTTPStatusError(url, 503)
        self.clock += timedelta(seconds=30)
        return fetch.Page(url, self.bodies[url], self.clock)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    fake = FakeWeb()
    monkeypatch.setattr(fetch, "polite_get", fake.get)
    return fake


def test_sources_are_tiered_and_polite() -> None:
    assert {s.tier for s in SOURCES} == {1, 2}
    assert BY_NAME["news_ids"].delay >= 10  # robots.txt crawl-delay 10
    assert all(s.url.startswith("https://") for s in SOURCES)


def test_poll_stores_new_content_and_skips_unchanged(web: FakeWeb, tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    sources = [BY_NAME["iu_crime_notices"], BY_NAME["news_ipm"]]
    first = poll(lake, sources, "r1", sleep=lambda _: None)
    assert first.stored == ["iu_crime_notices", "news_ipm"]
    assert first.items == {"news_ipm": 2}

    second = poll(lake, sources, "r2", sleep=lambda _: None)
    assert (second.stored, second.unchanged) == ([], ["iu_crime_notices", "news_ipm"])

    web.bodies[BY_NAME["news_ipm"].url] = FEED.replace(b"<title>b", b"<title>c")
    third = poll(lake, sources, "r3", sleep=lambda _: None)
    assert third.stored == ["news_ipm"]
    assert len(bronze.manifests(lake, "news_ipm")) == 2


def test_a_failing_source_does_not_stop_the_rest(web: FakeWeb, tmp_path: Path) -> None:
    web.down.add(BY_NAME["iu_emergency"].url)
    waits: list[float] = []
    result = poll(FileLake(tmp_path / "lake"), SOURCES, "r1", sleep=waits.append)
    assert result.failed == ["iu_emergency"]
    assert len(result.stored) == len(SOURCES) - 1
    assert 10.0 in waits


def test_cli_rejects_unknown_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LAKE_URI", (tmp_path / "lake").as_uri())
    with pytest.raises(SystemExit):
        cli.main(["--only", "news_ipm,twitter"])


def test_cli_polls_a_subset(web: FakeWeb, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LAKE_URI", (tmp_path / "lake").as_uri())
    monkeypatch.setattr("campus_safety.collectors.poll.time.sleep", lambda _: None)
    assert cli.main(["--only", "news_ipm"]) == 0
    assert len(bronze.manifests(FileLake(tmp_path / "lake"), "news_ipm")) == 1
