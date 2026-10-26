"""Keep a local history of the IU Bloomington daily crime log.

The page only shows 60 days, so `run` is scheduled daily. It saves the raw page before parsing
it: if IU changes the HTML, the snapshot survives and `rebuild` replays it after a fix.
"""

import argparse
import hashlib
import logging
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from campus_safety import fetch
from campus_safety.iu_crime_log import store
from campus_safety.iu_crime_log.classify import Severity
from campus_safety.iu_crime_log.parse import CrimeLog, ParseError, parse_crime_log

UNCLASSIFIED_FILE = Path("logs", "unclassified-offenses.txt")
URL = (
    "https://protect.iu.edu/iu-police-department/campus-security-reports/crime-log/daily-logs.html"
)

log = logging.getLogger("iu-crime-log")


def run(data_dir: Path, min_interval: timedelta) -> int:
    snapshots = store.list_snapshots(data_dir)
    if snapshots:
        last = store.snapshot_time(snapshots[-1])
        if datetime.now(UTC) - last < min_interval:
            log.info("skip: newest snapshot %s is under %s old", last.isoformat(), min_interval)
            return 0
    page = fetch.polite_get(URL)
    path = store.write_snapshot(data_dir, page.body, page.fetched_at)
    log.info("saved %s", path)
    crime_log = _parse(page.body)
    with closing(store.connect(data_dir / store.DB_NAME)) as conn:
        summary = store.ingest(
            conn,
            crime_log,
            fetched_at=page.fetched_at,
            snapshot=path.relative_to(data_dir).as_posix(),
            sha256=hashlib.sha256(page.body).hexdigest(),
        )
    _report(crime_log, data_dir / UNCLASSIFIED_FILE)
    log.info("run %d: %d new, %d changed", summary.run_id, summary.new, summary.changed)
    return 0


def check() -> int:
    crime_log = _parse(fetch.polite_get(URL).body)
    _report(crime_log, None)
    if not crime_log.incidents:
        log.error("parsed zero incidents; the page layout may have changed")
        return 1
    return 0


def rebuild(data_dir: Path) -> int:
    db = data_dir / store.DB_NAME
    fresh = db.with_name(f"{db.name}.rebuild")
    fresh.unlink(missing_ok=True)
    snapshots = store.list_snapshots(data_dir)
    skipped = 0
    with closing(store.connect(fresh)) as conn:
        for path in snapshots:
            body = store.read_snapshot(path)
            try:
                crime_log = _parse(body)
            except ParseError as e:
                log.warning("skip %s: %s", path, e)
                skipped += 1
                continue
            store.ingest(
                conn,
                crime_log,
                fetched_at=store.snapshot_time(path),
                snapshot=path.relative_to(data_dir).as_posix(),
                sha256=hashlib.sha256(body).hexdigest(),
            )
    fresh.replace(db)
    log.info("rebuilt %s from %d snapshots, %d skipped", db, len(snapshots) - skipped, skipped)
    return 1 if skipped else 0


def _parse(body: bytes) -> CrimeLog:
    return parse_crime_log(body.decode("utf-8", errors="replace"))


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
    unclassified_file.parent.mkdir(parents=True, exist_ok=True)
    known = set(unclassified_file.read_text().splitlines()) if unclassified_file.exists() else set()
    unclassified_file.write_text("".join(f"{label}\n" for label in sorted(known | unclassified)))
    log.warning(
        "%d unclassified offense labels; add rules in classify.py, see %s",
        len(unclassified),
        unclassified_file,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iu-crime-log", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="default: data")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="fetch, snapshot, parse, store (daily job)")
    run_parser.add_argument(
        "--min-interval-hours",
        type=float,
        default=12.0,
        help="skip when the newest snapshot is younger than this (default: 12)",
    )
    commands.add_parser("check", help="fetch and parse the live page, store nothing")
    commands.add_parser("rebuild", help="recreate the database from every saved snapshot")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "run":
            return run(args.data_dir, timedelta(hours=args.min_interval_hours))
        if args.command == "check":
            return check()
        return rebuild(args.data_dir)
    except (fetch.FetchError, ParseError) as e:
        log.error("%s", e)
        return 1
