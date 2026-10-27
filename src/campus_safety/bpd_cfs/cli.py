"""bpd-cfs: pull BPD calls for service into the lake's bronze layer (make transform parses it)."""

import argparse
import logging
import os
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety import fetch
from campus_safety.bpd_cfs.pull import pull
from campus_safety.lake import bronze
from campus_safety.lake.storage import LakeConfigError, open_lake

log = logging.getLogger("bpd-cfs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bpd-cfs", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pull", help="fetch every page and the dataset metadata into bronze")
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        summary = pull(open_lake(os.environ.get("LAKE_URI")), bronze.new_run_id())
    except (fetch.FetchError, LakeConfigError, ClientError, BotoCoreError, ValueError) as e:
        log.error("%s", e)
        return 1
    log.info("pulled %d rows in %d pages", summary.rows, summary.pages)
    return 0
