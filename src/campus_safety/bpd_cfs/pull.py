"""Pull BPD calls for service into bronze: every SODA page raw, plus the dataset's metadata.

Paging is ordered by Socrata's row id so pages are stable while we read. The metadata snapshot
(rowsUpdatedAt) is stored on every pull, so the refresh cadence emerges from bronze over time.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

from campus_safety import fetch
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

SOURCE = "bpd_calls_for_service"
METADATA_SOURCE = "bpd_calls_for_service_metadata"
DATASET = "t5xf-ggw6"
RESOURCE = f"https://data.bloomington.in.gov/resource/{DATASET}.json"
METADATA = f"https://data.bloomington.in.gov/api/views/{DATASET}.json"
PAGE_SIZE = 25_000
DELAY_SECONDS = 1.5  # the portal's robots.txt asks for a 1 s crawl delay


@dataclass(frozen=True)
class PullSummary:
    pages: int
    rows: int


def page_url(offset: int, limit: int = PAGE_SIZE) -> str:
    query = {"$limit": limit, "$offset": offset, "$order": ":id"}
    return f"{RESOURCE}?{urlencode(query)}"


def pull(
    lake: Lake,
    run_id: str,
    *,
    page_size: int = PAGE_SIZE,
    delay: float = DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> PullSummary:
    def store(source: str, url: str, part: str) -> bytes:
        page = fetch.polite_get(url)
        bronze.write(
            lake,
            source=source,
            body=page.body,
            url=url,
            fetched_at=page.fetched_at,
            http_status=page.status,
            run_id=f"{run_id}-{part}",
            ext="json",
        )
        sleep(delay)
        return page.body

    store(METADATA_SOURCE, METADATA, "meta")
    pages = rows = 0
    while True:
        records = json.loads(store(SOURCE, page_url(rows, page_size), f"p{pages:04d}"))
        if not isinstance(records, list):
            raise fetch.FetchError(f"page {pages}: expected a JSON array")
        pages += 1
        rows += len(records)
        if len(records) < page_size:
            return PullSummary(pages, rows)
