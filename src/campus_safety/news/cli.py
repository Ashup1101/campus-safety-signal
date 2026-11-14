"""news: fill the model cache for relevant items (Gemini free tier by default, or OpenAI on the
owner's prepaid credits; public news only, every run capped), score extractors against the
owner's ground truth, or report pipeline counts. Logs carry counts only."""

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety.env import load_keys
from campus_safety.lake.storage import LakeConfigError, open_lake
from campus_safety.news import evaluate, providers
from campus_safety.news.extract import CachedLLMExtractor, Extractor, RulesExtractor
from campus_safety.news.items import Item
from campus_safety.news.openai_api import Usage
from campus_safety.news.screen import screen
from campus_safety.news.silver import NewsSummary, stage, unique_items

log = logging.getLogger("news")
CACHE = Path("data", "cache", "news_llm")


def _items() -> tuple[list[Item], NewsSummary]:
    summary = NewsSummary()
    lake = open_lake(os.environ.get("LAKE_URI"))
    return unique_items(lake, summary), summary


def extract(cache: Path, provider: str, model: str, limit: int) -> int:
    found, summary = _items()
    usage = Usage()
    generate = providers.generator(provider, model, json_mode=True, usage=usage)
    extractor = CachedLLMExtractor(cache, model, generate)
    relevant = [i for i in found if screen(i.text).relevant]
    # Flagged items are extracted by rules only, so a model call on them would be wasted credit.
    safe = [i for i in relevant if not screen(i.text).injection_suspected]
    todo = [i for i in safe if not extractor.cached(screen(i.text).text)][:limit]
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
        except providers.ERRORS as e:
            log.error("%s after %d calls", e, extractor.calls)
            return 1
        answered += 1
        invalid += extraction is None
    log.info(
        "%s %s: %d calls, %d answers not valid, %d prompt + %d completion tokens",
        provider,
        model,
        answered,
        invalid,
        usage.prompt_tokens,
        usage.completion_tokens,
    )
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
    parser.add_argument("--provider", choices=providers.PROVIDERS, default="gemini")
    parser.add_argument("--model", default=None, help="default: the provider's pinned model")
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", help="ask the model about uncached items")
    extract_parser.add_argument("--limit", type=int, default=20, help="most model calls per run")
    eval_parser = commands.add_parser("eval", help="per-field precision/recall vs ground truth")
    eval_parser.add_argument("--truth", type=Path, default=evaluate.TRUTH)
    commands.add_parser("report", help="pipeline counts without a model call")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_keys()
    model = args.model or providers.default_model(args.provider)
    try:
        if args.command == "extract":
            return extract(args.cache, args.provider, model, args.limit)
        if args.command == "eval":
            return evaluate_all(args.truth, args.cache, model)
        return report(args.cache, model)
    except (LakeConfigError, ClientError, BotoCoreError, ValueError) as e:
        log.error("%s", e)
        return 1
