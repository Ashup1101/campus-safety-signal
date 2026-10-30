import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from campus_safety import fetch, wayback
from campus_safety.iu_crime_log import backfill
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake

PAGE_CDX = [
    ["timestamp", "original", "digest"],
    ["20241018100340", "https://protect.iu.edu/crime-log/daily-logs.html", "AAAA1111BBBB"],
    ["20250301000000", "https://protect.iu.edu/crime-log/daily-logs.html", "CCCC2222DDDD"],
]
PDF_CDX = [
    ["timestamp", "original", "digest"],
    [
        "20160402012732",
        "http://www.indiana.edu/~iupd/Documents/Daily%20Log/2-16-16.pdf",
        "EEEE3333",
    ],
    ["20160402012800", "http://www.indiana.edu/~iupd/Documents/Daily%20Log/", "FFFF4444"],
]


def test_cdx_parsing_and_raw_urls() -> None:
    (first, _) = wayback.parse_cdx(json.dumps(PAGE_CDX).encode())
    assert first.captured_at == datetime(2024, 10, 18, 10, 3, 40, tzinfo=UTC)
    assert first.raw_url == (
        "https://web.archive.org/web/20241018100340id_/https://protect.iu.edu/crime-log/daily-logs.html"
    )
    assert wayback.parse_cdx(b"") == []
    assert "collapse=urlkey" in wayback.cdx_url("x/", prefix=True)
    assert "collapse=digest" in wayback.cdx_url("x")


timeouts: list[object] = []


@pytest.fixture
def archive(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requested: list[str] = []
    timeouts.clear()

    def fake_polite_get(url: str, **kwargs: object) -> fetch.Page:
        requested.append(url)
        if url.startswith(wayback.CDX):
            timeouts.append(kwargs.get("timeout"))
        if url.startswith(wayback.CDX):
            rows = PDF_CDX if "matchType=prefix" in url else PAGE_CDX
            return fetch.Page(url, json.dumps(rows).encode(), datetime.now(UTC))
        if "20250301000000" in url:
            raise fetch.HTTPStatusError(url, 404)
        return fetch.Page(url, f"body of {url}".encode(), datetime.now(UTC))

    monkeypatch.setattr(fetch, "polite_get", fake_polite_get)
    return requested


def test_backfill_stores_captures_with_capture_times(archive: list[str], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    summary = backfill.backfill(lake, delay=0, sleep=lambda _: None)
    assert (summary.listed, summary.fetched, summary.present, summary.failed) == (3, 2, 0, 1)
    stored = bronze.manifests(lake, backfill.SOURCE)
    assert sorted(m.key.rsplit(".", 2)[1] for m in stored) == ["html", "pdf"]
    pdf = next(m for m in stored if m.key.endswith(".pdf.gz"))
    assert pdf.captured_at == datetime(2016, 4, 2, 1, 27, 32, tzinfo=UTC)
    assert pdf.run_id == "wb-20160402012732-EEEE3333"
    assert bronze.read(lake, pdf).startswith(
        b"body of https://web.archive.org/web/20160402012732id_/"
    )


def test_backfill_resumes_without_refetching(archive: list[str], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    backfill.backfill(lake, delay=0, sleep=lambda _: None)
    archive.clear()
    summary = backfill.backfill(lake, delay=0, sleep=lambda _: None)
    assert (summary.fetched, summary.present) == (0, 2)
    assert [url for url in archive if not url.startswith(wayback.CDX)] == [
        "https://web.archive.org/web/20250301000000id_/https://protect.iu.edu/crime-log/daily-logs.html"
    ]


def test_backfill_retries_when_the_archive_pushes_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    waits: list[float] = []

    def flaky(url: str, **kwargs: object) -> fetch.Page:
        calls.append(url)
        if url.startswith(wayback.CDX):
            rows = [PAGE_CDX[0], PAGE_CDX[1]] if "matchType" not in url else [PDF_CDX[0]]
            return fetch.Page(url, json.dumps(rows).encode(), datetime.now(UTC))
        if len([c for c in calls if not c.startswith(wayback.CDX)]) == 1:
            raise fetch.HTTPStatusError(url, 429)
        return fetch.Page(url, b"ok", datetime.now(UTC))

    monkeypatch.setattr(fetch, "polite_get", flaky)
    summary = backfill.backfill(FileLake(tmp_path / "lake"), delay=2, sleep=waits.append)
    assert (summary.fetched, summary.failed) == (1, 0)
    assert 30 in waits


def test_cdx_listings_are_per_year_with_a_long_timeout(archive: list[str], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    backfill.backfill(lake, delay=0, sleep=lambda _: None)
    listings = [url for url in archive if url.startswith(wayback.CDX)]
    assert set(timeouts) == {wayback.CDX_TIMEOUT_SECONDS}
    assert len(listings) == 1 + len(range(backfill.FIRST_CAPTURE_YEAR, datetime.now(UTC).year + 1))
    assert "from=2011&to=2011" in listings[2]
    assert len(bronze.manifests(lake, backfill.LISTING_SOURCE)) == len(listings)


def test_a_failed_listing_reuses_the_last_stored_one(
    archive: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lake = FileLake(tmp_path / "lake")
    backfill.backfill(lake, delay=0, sleep=lambda _: None)
    for manifest in bronze.manifests(lake, backfill.SOURCE):  # pretend the PDF never arrived
        if manifest.key.endswith(".pdf.gz"):
            (tmp_path / "lake" / bronze.manifest_key(manifest.key)).unlink()

    def listings_down(url: str, **kwargs: object) -> fetch.Page:
        if url.startswith(wayback.CDX):
            raise fetch.HTTPStatusError(url, 503)
        return fetch.Page(url, b"pdf again", datetime.now(UTC) + timedelta(hours=1))

    monkeypatch.setattr(fetch, "polite_get", listings_down)
    summary = backfill.backfill(lake, delay=0, sleep=lambda _: None)
    # From the stored listings: the missing PDF plus the capture that answered 404 the first time.
    assert (summary.listed, summary.fetched) == (3, 2)


def test_cdx_listing_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    attempts: list[str] = []

    def unavailable(url: str, **kwargs: object) -> fetch.Page:
        attempts.append(url)
        raise fetch.HTTPStatusError(url, 503)

    monkeypatch.setattr(fetch, "polite_get", unavailable)
    with pytest.raises(fetch.FetchError, match="every CDX listing failed"):
        backfill.backfill(FileLake(tmp_path / "lake"), delay=1, sleep=lambda _: None)
    assert len(attempts) == backfill.RETRIES * len(backfill._listing_urls())


def test_one_failed_year_does_not_stop_the_others(
    archive: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    working = fetch.polite_get

    def year_2013_down(url: str, **kwargs: object) -> fetch.Page:
        if "from=2013" in url:
            raise fetch.HTTPStatusError(url, 503)
        return working(url)

    monkeypatch.setattr(fetch, "polite_get", year_2013_down)
    summary = backfill.backfill(FileLake(tmp_path / "lake"), delay=0, sleep=lambda _: None)
    assert summary.listings_failed == 1
    assert summary.fetched == 2
