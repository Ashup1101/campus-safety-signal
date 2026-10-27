"""calibration: pull published aggregates (Clery data files, BPS packets) into bronze."""

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime

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
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("pull", help="Clery data files and Board of Public Safety packets")
    pull.add_argument(
        "--doe-years", type=years, default=years("2014-2025"), help="survey years, e.g. 2014-2025"
    )
    pull.add_argument(
        "--bps-years",
        type=years,
        default=years(f"2021-{this_year}"),
        help=f"meeting years, e.g. 2021-{this_year}",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        lake = open_lake(os.environ.get("LAKE_URI"))
        run_id = bronze.new_run_id()
        zips = doe.pull(lake, run_id, args.doe_years)
        packets = bps.pull(lake, run_id, args.bps_years)
    except (fetch.FetchError, LakeConfigError, ClientError, BotoCoreError, ValueError) as e:
        log.error("%s", e)
        return 1
    log.info("stored %d Clery data files and %d new meeting packets", zips, packets)
    return 0
