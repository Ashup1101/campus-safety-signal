"""t2: news relevance model. `train` runs on GitHub Actions only (never on the laptop); `import`
brings a finished run into the lake registry. Logs carry counts and scores only."""

import argparse
import logging
import os
import uuid
from collections.abc import Sequence
from pathlib import Path

import duckdb

log = logging.getLogger("t2")


def items(warehouse: Path) -> list[dict[str, object]]:
    """News items as the dataset needs them: title, short summary, time and the rule's label."""
    config: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
    with duckdb.connect(str(warehouse), read_only=True, config=config) as con:
        rows = con.execute(
            "select item_id, title, summary, coalesce(published_at, observed_at), relevant"
            " from silver.news_items"
        ).fetchall()
    keys = ("item_id", "title", "summary", "published_at", "relevant")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def train(warehouse: Path, out: Path, run_id: str) -> int:
    from campus_safety.t2 import dataset
    from campus_safety.t2 import train as t2_train

    found = items(warehouse)
    data = dataset.build(found, dataset.ground_truth())
    by_id = {str(i["item_id"]): bool(i["relevant"]) for i in found}
    rule = [by_id[r.item_id] for r in data.test]  # the rule's own label for each test row
    card = t2_train.run(data, rule, run_id, out)
    log.info(
        "t2 %s: method %s, train %d (weak %d), test %d, provisional %s",
        run_id, card["method"], card["train_rows"], card["weak_train_rows"], card["test_rows"],
        card["provisional"],
    )  # fmt: skip
    return 0


def import_dir(name: str, source: Path) -> int:
    """Check the weights, then copy the run into the lake registry (write-once)."""
    import json

    from campus_safety.lake.storage import open_lake
    from campus_safety.models import registry, text_model

    try:
        found = text_model.problems(json.loads((source / "model.json").read_text()))
        if found:
            log.error("%s import refused: %s", name, "; ".join(found))
            return 1
        status = registry.import_run(open_lake(os.environ.get("LAKE_URI")), name, source)
    except (OSError, ValueError) as e:
        log.error("%s import refused: %s", name, type(e).__name__)
        return 1
    log.info("%s import %s: %s", name, source.name, status)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="t2", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fit = commands.add_parser("train", help="fit and score (GitHub Actions only)")
    fit.add_argument("--warehouse", type=Path, default=Path("data/warehouse/warehouse.duckdb"))
    fit.add_argument("--out", type=Path, default=Path("data/t2/out"))
    fit.add_argument("--run-id", default=None)
    load = commands.add_parser("import", help="check a finished run and copy it into the lake")
    load.add_argument("source", type=Path, help="a downloaded artifact directory")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "import":
        return import_dir("t2", args.source)
    if args.command == "train":
        return train(args.warehouse, args.out, args.run_id or f"train-{uuid.uuid4().hex[:8]}")
    return 2
