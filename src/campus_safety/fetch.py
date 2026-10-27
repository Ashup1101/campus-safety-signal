"""Polite HTTP GET for public sources: identifying User-Agent, robots.txt first, bounded size."""

import http.client
import urllib.error
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from urllib.parse import urlsplit, urlunsplit

from campus_safety import __version__

USER_AGENT = (
    f"campus-safety-signal/{__version__} (+https://github.com/Ashup1101/campus-safety-signal)"
)
TIMEOUT_SECONDS = 30
MAX_BYTES = 20 * 1024 * 1024


class FetchError(RuntimeError):
    """The request failed, or returned something we refuse to use."""


class HTTPStatusError(FetchError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"GET {url} returned HTTP {status}")
        self.status = status


class RobotsDisallowedError(FetchError):
    """robots.txt forbids the URL, or could not be read, which we treat the same."""


@dataclass(frozen=True)
class Page:
    url: str
    body: bytes
    fetched_at: datetime
    status: int = 200


def decode_body(raw: bytes, content_encoding: str, max_bytes: int = MAX_BYTES) -> bytes:
    encoding = content_encoding.strip().lower()
    if encoding in ("", "identity"):
        return raw
    if encoding != "gzip":
        raise FetchError(f"unsupported Content-Encoding {content_encoding!r}")
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)  # 16+ expects a gzip header
    try:
        # Cap the output so a small compressed body can't inflate without limit.
        body = inflater.decompress(raw, max_bytes + 1)
    except zlib.error as e:
        raise FetchError(f"corrupt gzip body: {e}") from e
    if len(body) > max_bytes:
        raise FetchError(f"body exceeds {max_bytes} bytes once decompressed")
    if not inflater.eof:
        raise FetchError("truncated gzip body")
    return body


def get(url: str, max_bytes: int = MAX_BYTES) -> bytes:
    return _get(url, max_bytes)[1]


def _get(url: str, max_bytes: int) -> tuple[int, bytes]:
    if urlsplit(url).scheme != "https":
        raise FetchError(f"refusing non-https URL {url!r}")
    # https is enforced above, so no file:// or other handlers are reachable.
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            if urlsplit(response.geturl()).scheme != "https":
                raise FetchError(f"{url} redirected off https to {response.geturl()}")
            raw = response.read(max_bytes + 1)
            encoding = response.headers.get("Content-Encoding", "")
            status = response.status
    except urllib.error.HTTPError as e:
        raise HTTPStatusError(url, e.code) from e
    except (OSError, http.client.HTTPException) as e:
        raise FetchError(f"GET {url} failed: {e}") from e
    if len(raw) > max_bytes:
        raise FetchError(f"GET {url} body exceeds {max_bytes} bytes")
    return status, decode_body(raw, encoding, max_bytes)


def robots_allows(robots_txt: str, url: str) -> bool:
    rules = urllib.robotparser.RobotFileParser()
    rules.parse(robots_txt.splitlines())
    return rules.can_fetch(USER_AGENT, url)


@cache
def _robots_txt(robots_url: str) -> str | None:
    """robots.txt for a host, once per process; None means none exists (everything allowed)."""
    try:
        return get(robots_url).decode("utf-8", errors="replace")
    except HTTPStatusError as e:
        # RFC 9309: a missing robots.txt allows everything. Like CPython's robotparser, treat
        # 401/403 as a ban; 5xx means unreachable, which also bans.
        if 400 <= e.status < 500 and e.status not in (401, 403):
            return None
        raise RobotsDisallowedError(f"{robots_url} returned HTTP {e.status}") from e


def check_robots(url: str) -> None:
    parts = urlsplit(url)
    robots_txt = _robots_txt(urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", "")))
    if robots_txt is not None and not robots_allows(robots_txt, url):
        raise RobotsDisallowedError(f"robots.txt disallows {url}")


def polite_get(url: str, max_bytes: int = MAX_BYTES) -> Page:
    check_robots(url)
    status, body = _get(url, max_bytes)
    return Page(url=url, body=body, fetched_at=datetime.now(UTC), status=status)
