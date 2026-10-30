"""t3: build the T3-lite extraction dataset from bronze (counts only in the log)."""

import argparse
import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from campus_safety.lake.storage import LakeConfigError, open_lake

log = logging.getLogger("t3")


def export(out: Path) -> int:
    from campus_safety.t3.pairs import collect, split, write
    from campus_safety.t3.privacy import PersonScreen

    pairs, counts = collect(open_lake(os.environ.get("LAKE_URI")), PersonScreen().has_person)
    stats = write(split(pairs), counts, out)
    log.info("t3 export: %s", json.dumps(stats["counts"]))
    for name, info in stats["splits"].items():  # type: ignore[attr-defined]
        log.info("  %-15s %s", name, json.dumps(info))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="t3", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export_parser = commands.add_parser("export", help="pairs + time-based splits as JSONL")
    export_parser.add_argument("--out", type=Path, default=Path("data/t3"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return export(args.out)
    except LakeConfigError as e:
        log.error("%s", e)
        return 1
