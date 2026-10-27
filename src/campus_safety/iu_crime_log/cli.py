"""Capture the IU Bloomington daily crime log into the lake's bronze layer.

The page only shows 60 days, so `run` is scheduled daily (GitHub Actions, launchd as backup).
It writes the raw page to bronze before parsing it: if IU changes the HTML, the snapshot
survives and `make transform` replays it after a parser fix.
"""

import argparse
import gzip
import hashlib
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety import fetch
from campus_safety.iu_crime_log import backfill
from campus_safety.iu_crime_log.classify import Severity, record_unclassified
from campus_safety.iu_crime_log.parse import CrimeLog, ParseError, parse_crime_log
from campus_safety.iu_crime_log.silver import SOURCE
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake, LakeConfigError, ObjectExistsError, open_lake

UNCLASSIFIED_FILE = Path("logs", "unclassified-offenses.txt")
LEGACY_SNAPSHOTS = Path("raw", "iu_crime_log")  # pre-lake local snapshots
URL = (
    "https://protect.iu.edu/iu-police-department/campus-security-reports/crime-log/daily-logs.html"
)

log = logging.getLogger("iu-crime-log")


def run(lake: Lake, data_dir: Path, min_interval: timedelta) -> int:
    if min_interval:
        last = bronze.latest_fetch(lake, SOURCE)
        if last is not None and datetime.now(UTC) - last < min_interval:
            log.info("skip: newest snapshot %s is under %s old", last.isoformat(), min_interval)
            return 0
    page = fetch.polite_get(URL)
    manifest = bronze.write(
        lake,
        source=SOURCE,
        body=page.body,
        url=URL,
        fetched_at=page.fetched_at,
        http_status=page.status,
        run_id=bronze.new_run_id(),
        ext="html",
    )
    log.info("saved %s (%d bytes)", manifest.key, len(page.body))
    return _validate(_parse(page.body), data_dir / UNCLASSIFIED_FILE)


def check() -> int:
    return _validate(_parse(fetch.polite_get(URL).body), None)


def import_snapshots(lake: Lake, data_dir: Path) -> int:
    """Copy pre-lake snapshots into bronze, keeping their original fetch times. Re-runnable."""
    imported = present = 0
    for path in sorted((data_dir / LEGACY_SNAPSHOTS).glob("*/*.html.gz")):
        body = gzip.decompress(path.read_bytes())
        stamp = path.name.removesuffix(".html.gz")
        try:
            bronze.write(
                lake,
                source=SOURCE,
                body=body,
                url=URL,
                fetched_at=datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
                http_status=200,
                # Derived from the content, so a second import hits the same keys and stops.
                run_id=f"import-{hashlib.sha256(body).hexdigest()[:12]}",
                ext="html",
            )
            imported += 1
        except ObjectExistsError:
            present += 1
    log.info("imported %d snapshots, %d already in bronze", imported, present)
    return 0


def backfill_wayback(lake: Lake, delay: float, limit: int | None) -> int:
    summary = backfill.backfill(lake, delay=delay, limit=limit)
    log.info(
        "wayback: %d captures listed, %d fetched, %d already in bronze, %d failed",
        summary.listed,
        summary.fetched,
        summary.present,
        summary.failed,
    )
    return 0


def _parse(body: bytes) -> CrimeLog:
    return parse_crime_log(body.decode("utf-8", errors="replace"))


def _validate(crime_log: CrimeLog, unclassified_file: Path | None) -> int:
    _report(crime_log, unclassified_file)
    if not crime_log.incidents:
        log.error("parsed zero incidents; the page layout may have changed")
        return 1
    return 0


def _report(crime_log: CrimeLog, unclassified_file: Path | None) -> None:
    """Log counts only. Offense labels can be sensitive, so they go to a local file, not the log."""
    incidents = crime_log.incidents
    log.info(
        "%s window %s to %s: %d incidents in %d cases",
        crime_log.campus,
        crime_log.window_start,
        crime_log.window_end,
        len(incidents),
        len({incident.case_number for incident in incidents}),
    )
    unclassified = {i.offense for i in incidents if i.severity is Severity.UNCLASSIFIED}
    if not unclassified:
        return
    if unclassified_file is None:
        log.warning("%d unclassified offense labels; run locally to list them", len(unclassified))
        return
    record_unclassified(unclassified_file, unclassified)
    log.warning(
        "%d unclassified offense labels; add rules in classify.py, see %s",
        len(unclassified),
        unclassified_file,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iu-crime-log", description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="local state and logs (default: data)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="fetch to bronze, then validate (daily job)")
    run_parser.add_argument(
        "--min-interval-hours",
        type=float,
        default=12.0,
        help="skip if bronze has a snapshot younger than this; 0 never lists (default: 12)",
    )
    commands.add_parser("check", help="fetch and parse the live page, store nothing")
    commands.add_parser("import-snapshots", help="copy pre-lake data/raw snapshots into bronze")
    wayback_parser = commands.add_parser(
        "backfill-wayback", help="fetch archived captures and legacy PDFs into bronze"
    )
    wayback_parser.add_argument(
        "--delay", type=float, default=4.0, help="seconds between requests (default: 4)"
    )
    wayback_parser.add_argument("--limit", type=int, help="fetch at most this many captures")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "check":
            return check()
        lake = open_lake(os.environ.get("LAKE_URI"))
        if args.command == "run":
            return run(lake, args.data_dir, timedelta(hours=args.min_interval_hours))
        if args.command == "backfill-wayback":
            return backfill_wayback(lake, args.delay, args.limit)
        return import_snapshots(lake, args.data_dir)
    except (fetch.FetchError, ParseError, LakeConfigError, ClientError, BotoCoreError) as e:
        log.error("%s", e)
        return 1
