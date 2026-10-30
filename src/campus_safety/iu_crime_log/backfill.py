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
from datetime import UTC, datetime

from campus_safety import fetch, wayback
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

SOURCE = "iu_crime_log_wayback"
LISTING_SOURCE = (
    "wayback_cdx"  # CDX listings are raw responses too; a failed listing reuses the last one
)
FIRST_CAPTURE_YEAR = 2010
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


def _listing_urls() -> list[tuple[str, str]]:
    """(ext, CDX URL): one listing for today's page, one per capture year for the PDF prefix."""
    page, pdfs = TARGETS
    years = range(FIRST_CAPTURE_YEAR, datetime.now(UTC).year + 1)
    return [(page[0], wayback.cdx_url(page[1]))] + [
        (pdfs[0], wayback.cdx_url(pdfs[1], prefix=True, year=year)) for year in years
    ]


def captures(
    lake: Lake, run_id: str, sleep: Callable[[float], None], delay: float
) -> list[tuple[str, wayback.Capture]]:
    stored = {m.url: m for m in bronze.manifests(lake, LISTING_SOURCE)}  # newest wins
    found: dict[str, tuple[str, wayback.Capture]] = {}
    for number, (ext, listing_url) in enumerate(_listing_urls()):
        sleep(delay)
        listing = _get(listing_url, sleep, delay, timeout=wayback.CDX_TIMEOUT_SECONDS)
        if listing is not None:
            bronze.write(
                lake,
                source=LISTING_SOURCE,
                body=listing.body,
                url=listing_url,
                fetched_at=listing.fetched_at,
                http_status=listing.status,
                run_id=f"{run_id}-cdx{number:02d}",
                ext="json",
            )
            body = listing.body
        elif listing_url in stored:
            body = bronze.read(lake, stored[listing_url])
        else:
            raise fetch.FetchError(f"CDX listing failed after {RETRIES} attempts: {listing_url}")
        for capture in wayback.parse_cdx(body):
            if ext != "pdf" or capture.original.lower().endswith(".pdf"):
                found.setdefault(capture.raw_url, (ext, capture))
    return list(found.values())


def backfill(
    lake: Lake,
    *,
    delay: float,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillSummary:
    done = {manifest.url for manifest in bronze.manifests(lake, SOURCE)}
    listed = captures(lake, bronze.new_run_id(), sleep, delay)
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


def _get(
    url: str,
    sleep: Callable[[float], None],
    delay: float,
    timeout: float = fetch.TIMEOUT_SECONDS,
) -> fetch.Page | None:
    for attempt in range(1, RETRIES + 1):
        try:
            return fetch.polite_get(url, timeout=timeout)
        except fetch.HTTPStatusError as e:
            if e.status not in RETRY_STATUSES or attempt == RETRIES:
                return None
            sleep(max(delay, 1.0) * 15 * attempt)  # back off hard when the archive pushes back
        except fetch.RobotsDisallowedError:
            raise
        except fetch.FetchError:
            return None
    return None
