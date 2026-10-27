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
    commands.add_parser("backup-notes", help="copy CLAUDE.md and .notes/ to the lake bucket")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "backup-notes":
            return backup_notes(NOTES)
        return run_transform(args.work_dir, args.cache_dir)
    except (LakeConfigError, ClientError, BotoCoreError) as e:
        log.error("%s", e)
        return 1
