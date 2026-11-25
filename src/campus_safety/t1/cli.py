"""t1: the tonight forecaster. `table` builds the counts table from a warehouse, `rule` writes
a rule-only forecast (laptop), `train` fits the models first (GitHub Actions only). Logs carry
counts and scores only, never records."""

import argparse
import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

import duckdb

from campus_safety import events

log = logging.getLogger("t1")
DEFAULT_TABLE = Path("data/t1/train.parquet")
CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}


def table(warehouse: Path, out: Path) -> int:
    from campus_safety.t1 import table as t1_table

    with duckdb.connect(str(warehouse), read_only=True, config=CONFIG) as con:
        con.execute(
            "CREATE TEMP VIEW t1_calls AS"
            " SELECT called_at, nature, district FROM silver.bpd_calls_for_service"
        )
        rows = t1_table.build(con, events.event_nights(), out)
    log.info("t1 table: %d zone-nights", rows)
    return 0


def forecast_run(table_path: Path, out: Path, run_id: str, fit_models: bool) -> int:
    from campus_safety.t1 import pipeline

    card = pipeline.run(table_path, out, run_id, fit_models)
    scores = card["scores"]
    log.info(
        "t1 %s: method %s, split %s, scores %s", run_id, card["method"], card["split_rows"], scores
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="t1", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("table", help="counts table from a warehouse")
    build.add_argument("--warehouse", type=Path, default=Path("data/warehouse/warehouse.duckdb"))
    build.add_argument("--out", type=Path, default=DEFAULT_TABLE)
    for name, help_text in (
        ("rule", "rule-only forecast (laptop)"),
        ("train", "fit the models, then forecast (GitHub Actions only)"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--table", type=Path, default=DEFAULT_TABLE)
        sub.add_argument("--out", type=Path, default=Path(f"data/t1/{name}"))
        sub.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "table":
            return table(args.warehouse, args.out)
        if not args.table.exists():
            log.error("t1: no table at %s; run `t1 table` first", args.table)
            return 1
        run_id = args.run_id or f"{args.command}-{uuid.uuid4().hex[:8]}"
        return forecast_run(args.table, args.out, run_id, args.command == "train")
    except (duckdb.Error, ValueError) as e:
        log.error("t1 %s failed: %s", args.command, type(e).__name__)
        return 1
