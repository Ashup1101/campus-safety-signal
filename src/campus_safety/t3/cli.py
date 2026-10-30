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


def fallback_run(model: str, cache: Path) -> int:
    from campus_safety.t3 import fallback, ollama

    lake = open_lake(os.environ.get("LAKE_URI"))

    def chat(name: str, messages: list[dict[str, str]]) -> str:
        return ollama.chat(name, messages, json_mode=True)

    summary = fallback.run(lake, model, ollama.model_digest(model), cache, chat)
    log.info("t3 fallback: %s", json.dumps(summary.__dict__))
    return 0


def baseline(model: str, split_file: Path, out: Path, limit: int | None) -> int:
    """Zero-shot answers from a local Ollama model on one split, scored; answers go to `out`."""
    from campus_safety.t3 import ollama
    from campus_safety.t3.schema import messages
    from campus_safety.t3.score import score

    rows = [json.loads(line) for line in split_file.read_text().splitlines()][:limit]
    answers = [ollama.chat(model, messages(row["source"])) for row in rows]
    report = score(answers, [row["target"] for row in rows])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as file:
        for row, answer in zip(rows, answers, strict=True):
            file.write(json.dumps({"pair_id": row["pair_id"], "output": answer}) + "\n")
    log.info("t3 baseline %s on %s: %s", model, split_file.name, json.dumps(report.summary()))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="t3", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export_parser = commands.add_parser("export", help="pairs + time-based splits as JSONL")
    export_parser.add_argument("--out", type=Path, default=Path("data/t3"))
    fallback_parser = commands.add_parser(
        "fallback", help="local model over snapshots the rules could not read (eligible ones only)"
    )
    fallback_parser.add_argument("--model", default="campus-t3-lite")
    fallback_parser.add_argument("--cache", type=Path, default=Path("data/cache/llm_fallback"))
    baseline_parser = commands.add_parser(
        "baseline", help="zero-shot local Ollama model on a split"
    )
    baseline_parser.add_argument("--model", default="qwen2.5:1.5b-instruct")
    baseline_parser.add_argument("--split", type=Path, default=Path("data/t3/test.jsonl"))
    baseline_parser.add_argument("--out", type=Path, default=Path("data/t3/baseline_ollama.jsonl"))
    baseline_parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from campus_safety.t3.ollama import OllamaError

    try:
        if args.command == "fallback":
            return fallback_run(args.model, args.cache)
        if args.command == "baseline":
            return baseline(args.model, args.split, args.out, args.limit)
        return export(args.out)
    except (LakeConfigError, OllamaError) as e:
        log.error("%s", e)
        return 1
