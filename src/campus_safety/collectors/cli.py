"""collect: poll Phase 2a sources once into bronze (counts only in the log)."""

import argparse
import logging
import os
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety.collectors.poll import poll
from campus_safety.collectors.sources import BY_NAME, SOURCES
from campus_safety.lake import bronze
from campus_safety.lake.storage import LakeConfigError, open_lake

log = logging.getLogger("collect")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collect", description=__doc__)
    parser.add_argument(
        "--only", help=f"comma-separated subset of: {', '.join(BY_NAME)}", default=""
    )
    args = parser.parse_args(argv)
    names = [name for name in args.only.split(",") if name]
    if unknown := sorted(set(names) - BY_NAME.keys()):
        parser.error(f"unknown sources: {', '.join(unknown)}")
    sources = [BY_NAME[name] for name in names] if names else list(SOURCES)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = poll(open_lake(os.environ.get("LAKE_URI")), sources, bronze.new_run_id())
    except (LakeConfigError, ClientError, BotoCoreError) as e:
        log.error("%s", e)
        return 1
    log.info(
        "collect: %d stored, %d unchanged, %d failed; feed items %s",
        len(result.stored),
        len(result.unchanged),
        len(result.failed),
        result.items,
    )
    if result.failed:
        log.warning("failed sources: %s", ", ".join(result.failed))
    return 1 if len(result.failed) == len(sources) else 0
