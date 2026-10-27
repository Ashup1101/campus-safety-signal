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
        "--sources",
        default="doe,bps",
        help="comma-separated: doe (Clery data files), bps (meeting packets); default both",
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
    except LakeConfigError as e:
        log.error("%s", e)
        return 1
    run_id = bronze.new_run_id()
    pulls = {
        "doe": lambda: doe.pull(lake, run_id, args.doe_years),
        "bps": lambda: bps.pull(lake, run_id, args.bps_years),
    }
    names = args.sources.split(",")
    if unknown := sorted(set(names) - pulls.keys()):
        parser.error(f"unknown sources: {', '.join(unknown)}")
    failed = 0
    # Each source runs on its own: a site that bans us (robots.txt) must not stop the others.
    for name in names:
        try:
            log.info("%s: stored %d files", name, pulls[name]())
        except (fetch.FetchError, ClientError, BotoCoreError, ValueError) as e:
            log.error("%s: %s", name, e)
            failed += 1
    return 1 if failed else 0
