"""Internet Archive Wayback Machine: list captures through the CDX API, fetch them raw (id_)."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

CDX = "https://web.archive.org/cdx/search/cdx"
CDX_TIMEOUT_SECONDS = 180  # a prefix listing of ~1,000 URLs can take minutes to start answering


@dataclass(frozen=True)
class Capture:
    timestamp: str  # YYYYMMDDhhmmss, UTC
    original: str  # the URL as archived
    digest: str  # content hash from the archive

    @property
    def captured_at(self) -> datetime:
        return datetime.strptime(self.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)

    @property
    def raw_url(self) -> str:
        # id_ returns the archived bytes without the Wayback toolbar or link rewriting.
        return f"https://web.archive.org/web/{self.timestamp}id_/{self.original}"


def cdx_url(url: str, *, prefix: bool = False) -> str:
    """Successful captures of a URL (or every URL under a prefix), deduplicated by the archive."""
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,digest",
        "filter": "statuscode:200",
        # Prefix queries want one capture per URL; single pages, one per content change.
        "collapse": "urlkey" if prefix else "digest",
    }
    if prefix:
        params["matchType"] = "prefix"
    return f"{CDX}?{urlencode(params)}"


def parse_cdx(body: bytes) -> list[Capture]:
    rows = json.loads(body) if body.strip() else []
    if not rows:
        return []
    header, *data = rows
    column = {name: index for index, name in enumerate(header)}
    return [
        Capture(row[column["timestamp"]], row[column["original"]], row[column["digest"]])
        for row in data
    ]
