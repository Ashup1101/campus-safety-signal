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
    from campus_safety.t3.track import log_run

    sizes = {f"rows.{name}": float(info["rows"]) for name, info in stats["splits"].items()}  # type: ignore[attr-defined]
    log_run("export", stats, sizes, [out / "stats.json"])
    log.info("t3 export: %s", json.dumps(stats["counts"]))
    for name, info in stats["splits"].items():  # type: ignore[attr-defined]
        log.info("  %-15s %s", name, json.dumps(info))
    return 0


def fallback_run(model: str, cache: Path) -> int:
    from campus_safety.t3 import fallback, ollama

    lake = open_lake(os.environ.get("LAKE_URI"))

    def chat(name: str, messages: list[dict[str, str]]) -> str:
        return ollama.chat(name, messages, json_mode=True)

    digest = ollama.model_digest(model)
    summary = fallback.run(lake, model, digest, cache, chat)
    from campus_safety.t3.track import log_run

    log_run(
        "fallback",
        {"model": model, "digest": digest},
        {k: float(v) for k, v in summary.__dict__.items()},
    )
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
    from campus_safety.t3.track import log_run

    log_run(
        f"baseline-ollama-{model}", {"model": model, "split": split_file.name}, report.summary()
    )
    log.info("t3 baseline %s on %s: %s", model, split_file.name, json.dumps(report.summary()))
    return 0


def track_kaggle(outputs: Path) -> int:
    """Log a finished Kaggle run (run_info.json + metrics.json from the notebook) to MLflow."""
    from campus_safety.t3.track import kaggle_metrics, log_run

    run_info = json.loads((outputs / "run_info.json").read_text())
    metrics = kaggle_metrics(json.loads((outputs / "metrics.json").read_text()))
    metrics |= {
        k: float(run_info[k])
        for k in ("train_seconds", "train_loss", "gguf_seconds")
        if k in run_info
    }
    artifacts = [
        outputs / "metrics.json",
        outputs / "run_info.json",
        *outputs.glob("errors_*.json"),
    ]
    run_id = log_run("kaggle-qlora", run_info, metrics, artifacts)
    log.info("t3 track-kaggle: logged run %s with %d metrics", run_id, len(metrics))
    return 0


def import_kaggle(outputs: Path) -> int:
    """Register the owner's Kaggle run (run_info.json + metrics.json) in the lake model registry.
    The model weights (GGUF) stay out of the lake: they run in Ollama, never on this laptop. The
    switch stays on rules until verified rows exist (method "rules")."""
    import hashlib
    import os
    import shutil
    import tempfile

    from campus_safety.lake.storage import open_lake
    from campus_safety.models import registry
    from campus_safety.t3.track import kaggle_metrics

    if not (outputs / "run_info.json").exists() or not (outputs / "metrics.json").exists():
        log.info("t3 import: no Kaggle outputs at %s yet; the switch stays on rules", outputs)
        return 0
    run_info = json.loads((outputs / "run_info.json").read_text())
    metrics = kaggle_metrics(json.loads((outputs / "metrics.json").read_text()))
    if not isinstance(run_info, dict):
        log.error("t3 import refused: run_info.json is not an object")
        return 1
    digest = hashlib.sha256((outputs / "metrics.json").read_bytes()).hexdigest()[:10]
    card = {
        "run_id": f"kaggle-{digest}",
        "method": "rules",  # until verified fallback rows exist
        "trained_at": str(run_info.get("finished_at") or ""),
        "scores": metrics,
    }
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        for name in ("run_info.json", "metrics.json"):
            shutil.copyfile(outputs / name, staging / name)
        (staging / "scorecard.json").write_text(json.dumps(card, sort_keys=True))
        status = registry.import_run(open_lake(os.environ.get("LAKE_URI")), "t3", staging)
    log.info("t3 import %s: %s (%d metrics)", card["run_id"], status, len(metrics))
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
    track_parser = commands.add_parser("track-kaggle", help="log the notebook's outputs to MLflow")
    track_parser.add_argument("outputs", type=Path, help="the downloaded t3_outputs folder")
    import_parser = commands.add_parser("import", help="register the Kaggle run in the lake")
    import_parser.add_argument("outputs", type=Path, nargs="?", default=Path("data/t3/kaggle"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from campus_safety.t3.ollama import OllamaError

    try:
        if args.command == "fallback":
            return fallback_run(args.model, args.cache)
        if args.command == "baseline":
            return baseline(args.model, args.split, args.out, args.limit)
        if args.command == "track-kaggle":
            return track_kaggle(args.outputs)
        if args.command == "import":
            return import_kaggle(args.outputs)
        return export(args.out)
    except (LakeConfigError, OllamaError) as e:
        log.error("%s", e)
        return 1
