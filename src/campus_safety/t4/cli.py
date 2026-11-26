"""t4: prompt-injection screen. `train` runs on GitHub Actions only; `import` brings a finished
run into the lake registry. Logs carry counts and scores only."""

import argparse
import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger("t4")


def train(out: Path, run_id: str) -> int:
    from campus_safety.t4 import dataset
    from campus_safety.t4 import train as t4_train

    card = t4_train.run(dataset.build(), run_id, out)
    log.info("t4 %s: method %s, scores %s", run_id, card["method"], card["scores"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="t4", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fit = commands.add_parser("train", help="fit and score (GitHub Actions only)")
    fit.add_argument("--out", type=Path, default=Path("data/t4/out"))
    fit.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "train":
        return train(args.out, args.run_id or f"train-{uuid.uuid4().hex[:8]}")
    return 2
