"""lake: replay bronze into silver (make transform)."""

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from campus_safety.lake.storage import LakeConfigError, open_lake

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lake", description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("data/warehouse"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/lake"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("transform", help="parse all bronze, dbt build, publish silver")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run_transform(args.work_dir, args.cache_dir)
    except LakeConfigError as e:
        log.error("%s", e)
        return 1
