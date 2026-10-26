import gzip

import pytest

from campus_safety import fetch
from campus_safety.fetch import (
    FetchError,
    HTTPStatusError,
    RobotsDisallowedError,
    check_robots,
    decode_body,
    robots_allows,
)

LOG_URL = "https://protect.example.edu/police/crime-log/daily-logs.html"
ROBOTS = """
User-agent: AdsBot-Google
Allow: /campaigns/

User-agent: *
Disallow: /_assets/
Disallow: /*.file-extension$
"""


def test_decode_body_passes_identity_through() -> None:
    assert decode_body(b"<html>", "") == b"<html>"


def test_decode_body_inflates_gzip() -> None:
    assert decode_body(gzip.compress(b"<html>"), "gzip") == b"<html>"


def test_decode_body_caps_inflated_size() -> None:
    bomb = gzip.compress(b"\0" * 10_000)
    with pytest.raises(FetchError, match="exceeds"):
        decode_body(bomb, "gzip", max_bytes=1_000)


@pytest.mark.parametrize("raw", [b"not gzip", gzip.compress(b"<html>" * 100)[:-12]])
def test_decode_body_rejects_corrupt_or_truncated_gzip(raw: bytes) -> None:
    with pytest.raises(FetchError):
        decode_body(raw, "gzip")


def test_decode_body_rejects_unknown_encoding() -> None:
    with pytest.raises(FetchError, match="unsupported"):
        decode_body(b"x", "br")


def test_get_refuses_plain_http() -> None:
    with pytest.raises(FetchError, match="non-https"):
        fetch.get("http://protect.example.edu/")


def test_robots_allows_log_path_and_blocks_disallowed() -> None:
    assert robots_allows(ROBOTS, LOG_URL)
    assert not robots_allows(ROBOTS, "https://protect.example.edu/_assets/app.js")


def test_robots_blocks_everything_for_named_agent() -> None:
    ours = "User-agent: campus-safety-signal\nDisallow: /\n"
    assert not robots_allows(ours, LOG_URL)


def _robots_status(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    def fake_get(url: str, max_bytes: int = fetch.MAX_BYTES) -> bytes:
        raise HTTPStatusError(url, status)

    monkeypatch.setattr(fetch, "get", fake_get)


def test_missing_robots_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    _robots_status(monkeypatch, 404)
    check_robots(LOG_URL)


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_forbidden_or_unreachable_robots_blocks(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _robots_status(monkeypatch, status)
    with pytest.raises(RobotsDisallowedError):
        check_robots(LOG_URL)


def test_check_robots_fetches_site_root_robots(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def fake_get(url: str, max_bytes: int = fetch.MAX_BYTES) -> bytes:
        requested.append(url)
        return b"User-agent: *\nDisallow: /police/\n"

    monkeypatch.setattr(fetch, "get", fake_get)
    with pytest.raises(RobotsDisallowedError):
        check_robots(LOG_URL)
    assert requested == ["https://protect.example.edu/robots.txt"]
