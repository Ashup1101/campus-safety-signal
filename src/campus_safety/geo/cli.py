"""geo: pull the city's public map layers into bronze (polite fetch, stored only when changed).
`make transform` turns the newest copy into silver/gold. Logs carry counts only."""

import argparse
import logging
import os
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety import fetch
from campus_safety.geo import zones
from campus_safety.lake import bronze
from campus_safety.lake.storage import LakeConfigError, open_lake

log = logging.getLogger("geo")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="geo", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pull", help="police reporting zones (Law Reporting Zones layer)")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        stored, count = zones.pull(open_lake(os.environ.get("LAKE_URI")), bronze.new_run_id())
    except (fetch.FetchError, zones.ZonesError, LakeConfigError, ClientError, BotoCoreError) as e:
        log.error("%s", e)
        return 1
    log.info("%d reporting zones; %s", count, "stored a new copy" if stored else "unchanged")
    return 0
