"""synthetic: patch a registered gap (generate), build the news eval set (news-eval), or phone
traces (traces). Everything is seeded and labeled; rows carry gap_id and seed. Counts only."""

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from campus_safety import gaps
from campus_safety.lake import bronze
from campus_safety.lake.storage import LakeConfigError, ObjectExistsError, open_lake
from campus_safety.news.extract import CachedLLMExtractor, Extractor, RulesExtractor
from campus_safety.synthetic import generate, news, profile, store, traces

log = logging.getLogger("synthetic")
OUT = Path("data", "synthetic")
WAREHOUSE = Path("data", "warehouse", "warehouse.duckdb")
DEMO_ZONE = traces.Zone(39.16655, -86.5290, 120.0)  # Kirkwood 400 block, demo-scale radius


def _gap(gap_id: str) -> gaps.Gap:
    register = {g.gap_id: g for g in gaps.load()}
    if gap_id not in register:
        raise ValueError(f"unknown gap_id {gap_id!r}; see configs/gaps.yaml")
    return register[gap_id]


def generate_patch(gap_id: str, seed: int, warehouse: Path, work: Path) -> int:
    gap = _gap(gap_id)
    if gap.segment.start is None or gap.segment.end is None:
        raise ValueError(f"{gap_id} has no date range to patch")
    found = profile.from_warehouse(warehouse, gap.segment.start, gap.segment.end)
    incidents, anomalies = generate.generate(gap, found, seed)
    lake = open_lake(os.environ.get("LAKE_URI"))
    try:
        patch = store.write(
            lake,
            work / gap_id / str(seed),
            gap_id,
            seed,
            bronze.new_run_id(),
            incidents,
            anomalies,
            found,
        )
    except ObjectExistsError:
        log.error("%s seed %d already exists in the lake; pick another seed", gap_id, seed)
        return 1
    log.info(
        "%s seed %d: %d incidents, %d anomalies, profile %s (%.0f per year), %s to %s",
        gap_id,
        seed,
        patch.incidents,
        patch.anomalies,
        patch.profile_origin,
        patch.yearly_total,
        gap.segment.start,
        gap.segment.end,
    )
    return 0


def news_eval(
    gap_id: str, seed: int, size: int, warehouse: Path, out: Path, cache: Path, model: str
) -> int:
    gap = _gap(gap_id)
    if gap.segment.start is None or gap.segment.end is None:
        raise ValueError(f"{gap_id} has no date range")
    found = profile.from_warehouse(warehouse, gap.segment.start, gap.segment.end)
    incidents, _ = generate.generate(gap, found, seed)
    items = news.build(incidents, seed, size)
    path = out / "news_eval" / f"seed={seed}.jsonl"
    news.save(items, path)
    from campus_safety.news import evaluate

    by_url = {e.item.url: e.item for e in items}
    truth = [e.truth for e in items]
    extractors: list[Extractor] = [RulesExtractor(), CachedLLMExtractor(cache, model)]
    log.info(
        "%d items (%d adversarial) -> %s",
        len(items),
        sum(e.owasp_id is not None for e in items),
        path,
    )
    for extractor in extractors:
        for line in evaluate.lines(evaluate.evaluate(extractor, truth, by_url)):
            log.info("%s", line)
        attack = news.attack_report(extractor, items)
        log.info(
            "%s: %d adversarial, %d resisted, %d hijacked, %d flagged by screening",
            attack.extractor,
            attack.adversarial,
            attack.resisted,
            attack.hijacked,
            attack.flagged,
        )
    return 0


def make_traces(seed: int, walkers: int, out: Path) -> int:
    rows = traces.walk(seed, walkers, DEMO_ZONE, datetime(2026, 1, 1, 22))
    path = out / "traces" / f"seed={seed}.parquet"
    traces.save(rows, path)
    bands = {b: sum(1 for r in rows if r[9] == b) for b in ("inside", "nearby", "away")}
    log.info("%d walkers, %d points, bands %s -> %s", walkers, len(rows), bands, path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthetic", description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--warehouse", type=Path, default=WAREHOUSE)
    parser.add_argument("--out", type=Path, default=OUT)
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="patch one registered gap into the lake")
    gen.add_argument("gap_id")
    ev = commands.add_parser("news-eval", help="templated items + truth + adversarial payloads")
    ev.add_argument("gap_id")
    ev.add_argument("--size", type=int, default=60)
    ev.add_argument("--cache", type=Path, default=Path("data/cache/news_llm"))
    ev.add_argument("--model", default=os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash")
    tr = commands.add_parser("traces", help="phone traces with expected bands")
    tr.add_argument("--walkers", type=int, default=5)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "generate":
            return generate_patch(args.gap_id, args.seed, args.warehouse, args.out / "work")
        if args.command == "news-eval":
            return news_eval(
                args.gap_id, args.seed, args.size, args.warehouse, args.out, args.cache, args.model
            )
        return make_traces(args.seed, args.walkers, args.out)
    except (LakeConfigError, ClientError, BotoCoreError, ValueError, gaps.GapRegisterError) as e:
        log.error("%s", e)
        return 1
