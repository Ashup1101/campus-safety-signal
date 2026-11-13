"""news: fill the model cache for relevant items (Gemini, public news only), score extractors
against the owner's ground truth, or report pipeline counts. Logs carry counts only."""

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety.lake.storage import LakeConfigError, open_lake
from campus_safety.news import evaluate, gemini
from campus_safety.news.extract import CachedLLMExtractor, Extractor, RulesExtractor
from campus_safety.news.items import Item
from campus_safety.news.screen import screen
from campus_safety.news.silver import NewsSummary, stage, unique_items

log = logging.getLogger("news")
CACHE = Path("data", "cache", "news_llm")


def _items() -> tuple[list[Item], NewsSummary]:
    summary = NewsSummary()
    lake = open_lake(os.environ.get("LAKE_URI"))
    return unique_items(lake, summary), summary


def extract(cache: Path, model: str, limit: int) -> int:
    found, summary = _items()
    extractor = CachedLLMExtractor(cache, model, gemini.generate)
    relevant = [i for i in found if screen(i.text).relevant]
    todo = [i for i in relevant if not extractor.cached(screen(i.text).text)][:limit]
    log.info(
        "%d items, %d relevant, %d to extract (cached: %d)",
        summary.items,
        len(relevant),
        len(todo),
        len(relevant) - len(todo),
    )
    answered = invalid = 0
    for item in todo:
        try:
            extraction = extractor.extract(screen(item.text).text, item.published_at)
        except gemini.GeminiError as e:
            log.error("%s after %d calls", e, extractor.calls)
            return 1
        answered += 1
        invalid += extraction is None
    log.info("%d model calls, %d answers not valid", answered, invalid)
    return 0


def evaluate_all(truth_path: Path, cache: Path, model: str) -> int:
    if not truth_path.exists():
        log.error("no ground truth at %s (see news.evaluate for the format)", truth_path)
        return 1
    found, _ = _items()
    by_url = {i.url: i for i in found}
    truth = evaluate.load_truth(truth_path)
    extractors: list[Extractor] = [RulesExtractor(), CachedLLMExtractor(cache, model)]
    for extractor in extractors:
        for line in evaluate.lines(evaluate.evaluate(extractor, truth, by_url)):
            log.info("%s", line)
    return 0


def report(cache: Path, model: str) -> int:
    found, summary = _items()
    extractors: list[Extractor] = [RulesExtractor(), CachedLLMExtractor(cache, model)]
    _, summary = stage(found, extractors, lambda text: text, datetime.now(UTC), summary)
    log.info(
        "%d pages (%d unreadable), %d items, %d relevant, %d incidents, %d clusters, %d confirmed,"
        " %d injection-suspected, %d ungrounded model answers",
        summary.pages,
        summary.layout_errors,
        summary.items,
        summary.relevant,
        summary.incidents,
        summary.clusters,
        summary.confirmed,
        summary.injection_suspected,
        summary.ungrounded,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="news", description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--model", default=gemini.model_name())
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", help="ask the model about uncached items")
    extract_parser.add_argument("--limit", type=int, default=200)
    eval_parser = commands.add_parser("eval", help="per-field precision/recall vs ground truth")
    eval_parser.add_argument("--truth", type=Path, default=evaluate.TRUTH)
    commands.add_parser("report", help="pipeline counts without a model call")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "extract":
            return extract(args.cache, args.model, args.limit)
        if args.command == "eval":
            return evaluate_all(args.truth, args.cache, args.model)
        return report(args.cache, args.model)
    except (LakeConfigError, ClientError, BotoCoreError, ValueError) as e:
        log.error("%s", e)
        return 1
