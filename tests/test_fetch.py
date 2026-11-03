import gzip
import ssl
from email.message import Message

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


@pytest.fixture(autouse=True)
def fresh_robots_cache() -> None:
    fetch._robots_txt.cache_clear()


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


def test_robots_txt_is_fetched_once_per_host(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def fake_get(url: str, max_bytes: int = fetch.MAX_BYTES) -> bytes:
        requested.append(url)
        return ROBOTS.encode()

    monkeypatch.setattr(fetch, "get", fake_get)
    check_robots(LOG_URL)
    check_robots("https://protect.example.edu/police/other.html")
    check_robots("https://web.example.org/web/1id_/x")
    assert requested == [
        "https://protect.example.edu/robots.txt",
        "https://web.example.org/robots.txt",
    ]


def test_tls_context_adds_intermediates_without_new_roots() -> None:
    context = fetch.tls_context()
    assert not context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    bare = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    bare.load_verify_locations(cadata=fetch.INTERMEDIATES.read_text())
    certs = bare.get_ca_certs()
    assert len(certs) == 2
    assert all(c["subject"] != c["issuer"] for c in certs)  # none is self-signed


def test_conditional_get_returns_304_as_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, str] | None] = []

    def fake_get(
        url: str, max_bytes: int, timeout: float, extra: dict[str, str] | None = None
    ) -> tuple[int, bytes, Message]:
        sent.append(extra)
        return 304, b"", Message()

    monkeypatch.setattr(fetch, "check_robots", lambda url: None)
    monkeypatch.setattr(fetch, "_get", fake_get)
    page = fetch.polite_get("https://example.org/x", etag='"a"', last_modified="Sun")
    assert (page.status, page.body, page.etag, page.last_modified) == (304, b"", '"a"', "Sun")
    assert sent == [{"If-None-Match": '"a"', "If-Modified-Since": "Sun"}]
