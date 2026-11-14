"""Poll every source once: fetch politely, store the raw response in bronze unless it is
byte-identical to the newest stored copy (frequent polls would otherwise duplicate unchanged
pages). Logs and summaries carry counts only.
"""

import hashlib
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from campus_safety import fetch
from campus_safety.collectors.sources import Source
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

# Items in a feed or sitemap, counted without parsing untrusted XML.
_ITEMS = re.compile(rb"<(?:item|entry|url)[\s>]")


@dataclass
class PollResult:
    stored: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)  # source -> error type (+ HTTP status)
    items: dict[str, int] = field(default_factory=dict)


def newest_sha256(lake: Lake, source: str) -> str | None:
    found = bronze.manifests(lake, source)
    return found[-1].sha256 if found else None


def poll(
    lake: Lake,
    sources: Iterable[Source],
    run_id: str,
    sleep: Callable[[float], None] | None = None,
) -> PollResult:
    wait = sleep or time.sleep
    result = PollResult()
    for source in sources:
        try:
            page = fetch.polite_get(source.url)
        except fetch.FetchError as e:
            result.failed.append(source.name)
            status = getattr(e, "status", None)
            inner = getattr(e.__cause__, "reason", None)  # URLError wraps the socket/TLS error
            cause = "".join(
                f"({type(x).__name__})"
                for x in (e.__cause__, inner)
                if isinstance(x, BaseException)
            )
            result.reasons[source.name] = (
                type(e).__name__ + cause + (f" {status}" if status else "")
            )
            wait(source.delay)
            continue
        if source.ext == "xml":
            result.items[source.name] = len(_ITEMS.findall(page.body))
        if hashlib.sha256(page.body).hexdigest() == newest_sha256(lake, source.name):
            result.unchanged.append(source.name)
        else:
            bronze.write(
                lake,
                source=source.name,
                body=page.body,
                url=source.url,
                fetched_at=page.fetched_at,
                http_status=page.status,
                run_id=run_id,
                ext=source.ext,
            )
            result.stored.append(source.name)
        wait(source.delay)
    return result
