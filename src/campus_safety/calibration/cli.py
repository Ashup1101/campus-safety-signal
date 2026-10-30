"""calibration: published aggregates into bronze; make transform builds silver.calibration_*."""

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety import fetch
from campus_safety.calibration import bps, doe
from campus_safety.lake import bronze
from campus_safety.lake.storage import LakeConfigError, open_lake

log = logging.getLogger("calibration")


def years(text: str) -> range:
    first, _, last = text.partition("-")
    return range(int(first), int(last or first) + 1)


def main(argv: Sequence[str] | None = None) -> int:
    this_year = datetime.now(UTC).year
    parser = argparse.ArgumentParser(prog="calibration", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="default: data")
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("pull", help="fetch Board of Public Safety meeting packets")
    pull.add_argument(
        "--bps-years",
        type=years,
        default=years(f"2021-{this_year}"),
        help=f"meeting years, e.g. 2021-{this_year}",
    )
    commands.add_parser(
        "import-doe",
        help=f"copy hand-downloaded Clery zips from <data-dir>/{doe.MANUAL_DIR} (never fetches)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        lake = open_lake(os.environ.get("LAKE_URI"))
        if args.command == "import-doe":
            summary = doe.import_manual(lake, args.data_dir)
            log.info(
                "doe: imported %d zips, %d already in bronze, %d files skipped",
                summary.imported,
                summary.present,
                summary.skipped,
            )
            return 0
        log.info("bps: stored %d packets", bps.pull(lake, bronze.new_run_id(), args.bps_years))
        return 0
    except (fetch.FetchError, LakeConfigError, ClientError, BotoCoreError, ValueError) as e:
        log.error("%s", e)
        return 1
