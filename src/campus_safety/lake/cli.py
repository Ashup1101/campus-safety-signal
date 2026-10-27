"""lake: replay bronze into silver (make transform), back up local notes (make backup)."""

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety.lake.storage import LakeConfigError, S3Lake, open_lake

NOTES = (Path("CLAUDE.md"), Path(".notes"))

log = logging.getLogger("lake")


def run_transform(work_dir: Path, cache_dir: Path) -> int:
    # Imported here: duckdb and dbt live in the transform group, not in the ingest install.
    from campus_safety.iu_crime_log.classify import record_unclassified
    from campus_safety.lake.transform import TransformError, transform

    lake = open_lake(os.environ.get("LAKE_URI"), cache_dir)
    try:
        summary = transform(lake, work_dir)
    except TransformError as e:
        log.error("%s", e)
        return 1
    log.info(
        "%d snapshots (%d failed to parse) -> %d incidents in %d cases, %d history rows",
        summary.snapshots,
        summary.parse_errors,
        summary.incidents,
        summary.cases,
        summary.history_rows,
    )
    for dataset in sorted({row[0] for row in summary.coverage}):
        rows = [row for row in summary.coverage if row[0] == dataset]
        covered = sum(row[4] for row in rows if row[1] == "covered")
        gaps = [row for row in rows if row[1] == "gap"]
        log.info(
            "coverage %s: %s to %s, %d days covered, %d gaps (%d days)",
            dataset,
            min(row[2] for row in rows),
            max(row[3] for row in rows),
            covered,
            len(gaps),
            sum(row[4] for row in gaps),
        )
    if summary.unclassified:
        labels_file = work_dir.parent / "logs" / "unclassified-offenses.txt"
        record_unclassified(labels_file, summary.unclassified)
        log.warning(
            "%d unclassified offense labels, see %s", len(summary.unclassified), labels_file
        )
    return 0


def print_coverage(work_dir: Path) -> int:
    """Covered ranges and gaps from the last transform: dates and day counts only."""
    import duckdb

    warehouse = work_dir / "warehouse.duckdb"
    if not warehouse.exists():
        raise LakeConfigError(f"no warehouse at {warehouse}; run make transform first")
    # Default (read-write) mode: DuckDB refuses mixed modes within one process.
    with duckdb.connect(str(warehouse)) as con:
        rows = con.execute(
            "SELECT * FROM gold.iu_crime_log_coverage ORDER BY dataset, range_start"
        ).fetchall()
    for dataset, kind, start, end, days in rows:
        print(f"{dataset:22} {kind:8} {start} {end} {days:5d}")
    return 0


def backup_notes(paths: Sequence[Path]) -> int:
    """Copy the local-only notes to s3://<lake bucket>/_private/notes/; versioning keeps history."""
    parts = urlsplit(os.environ.get("LAKE_URI", ""))
    if parts.scheme != "s3" or not parts.netloc:
        raise LakeConfigError("make backup needs LAKE_URI=s3://<bucket>/lake in .env")
    target = S3Lake(parts.netloc, "_private/notes")
    files = sorted(
        file
        for path in paths
        for file in ([path] if path.is_file() else path.rglob("*"))
        if file.is_file()
    )
    for file in files:
        target.put(file.as_posix(), file.read_bytes())
    log.info("backed up %d files to %s", len(files), target.uri)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lake", description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("data/warehouse"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/lake"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("transform", help="parse all bronze, dbt build, publish silver")
    commands.add_parser("coverage", help="print covered date ranges and gaps (last transform)")
    commands.add_parser("backup-notes", help="copy CLAUDE.md and .notes/ to the lake bucket")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "backup-notes":
            return backup_notes(NOTES)
        if args.command == "coverage":
            return print_coverage(args.work_dir)
        return run_transform(args.work_dir, args.cache_dir)
    except (LakeConfigError, ClientError, BotoCoreError) as e:
        log.error("%s", e)
        return 1
