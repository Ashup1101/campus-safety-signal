"""Backfill the IU crime log from the Wayback Machine into bronze (source iu_crime_log_wayback).

Two archived sources: captures of today's page (parsed by parse.py) and the daily PDFs that the
pre-2018 page linked to (parsed by legacy.py). The legacy index page itself only lists those
PDFs, so it is not stored. Requests are spaced out, and captures already in bronze are skipped,
so an interrupted backfill resumes where it stopped.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from campus_safety import fetch, wayback
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

SOURCE = "iu_crime_log_wayback"
TARGETS = (
    (
        "html",
        "protect.iu.edu/iu-police-department/campus-security-reports/crime-log/daily-logs.html",
    ),
    ("pdf", "indiana.edu/~iupd/Documents/Daily"),
)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRIES = 3

log = logging.getLogger("iu-crime-log")


@dataclass(frozen=True)
class BackfillSummary:
    listed: int
    fetched: int
    present: int
    failed: int


def captures() -> list[tuple[str, wayback.Capture]]:
    found: list[tuple[str, wayback.Capture]] = []
    for ext, url in TARGETS:
        listing = fetch.polite_get(wayback.cdx_url(url, prefix=ext == "pdf"))
        found += [
            (ext, capture)
            for capture in wayback.parse_cdx(listing.body)
            if ext != "pdf" or capture.original.lower().endswith(".pdf")
        ]
    return found


def backfill(
    lake: Lake,
    *,
    delay: float,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillSummary:
    done = {manifest.url for manifest in bronze.manifests(lake, SOURCE)}
    listed = captures()
    todo = [(ext, c) for ext, c in listed if c.raw_url not in done][:limit]
    fetched = failed = 0
    for number, (ext, capture) in enumerate(todo, 1):
        sleep(delay)
        page = _get(capture.raw_url, sleep, delay)
        if page is None:
            failed += 1
            continue
        bronze.write(
            lake,
            source=SOURCE,
            body=page.body,
            url=capture.raw_url,
            fetched_at=page.fetched_at,
            http_status=page.status,
            run_id=f"wb-{capture.timestamp}-{capture.digest[:10]}",
            ext=ext,
            captured_at=capture.captured_at,
        )
        fetched += 1
        if number % 50 == 0:
            log.info("backfill progress: %d of %d", number, len(todo))
    present = sum(1 for _, capture in listed if capture.raw_url in done)
    return BackfillSummary(len(listed), fetched, present, failed)


def _get(url: str, sleep: Callable[[float], None], delay: float) -> fetch.Page | None:
    for attempt in range(1, RETRIES + 1):
        try:
            return fetch.polite_get(url)
        except fetch.HTTPStatusError as e:
            if e.status not in RETRY_STATUSES or attempt == RETRIES:
                return None
            sleep(max(delay, 1.0) * 15 * attempt)  # back off hard when the archive pushes back
        except fetch.RobotsDisallowedError:
            raise
        except fetch.FetchError:
            return None
    return None
