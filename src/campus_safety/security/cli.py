"""redteam: run the corpus with a worst-case (fully obedient) model and print pass counts per
OWASP id. Exit 1 if any defense fails. No network, no paid model, ids and verdicts only."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from campus_safety.security import redteam

log = logging.getLogger("redteam")


def t4_line() -> None:
    """T4 next to the injection rule on the corpus and harmless texts, when a T4 run is imported."""
    import os

    from campus_safety.lake.storage import LakeConfigError, open_lake
    from campus_safety.models import gates, registry
    from campus_safety.t4 import dataset, train

    try:
        lake = open_lake(os.environ.get("LAKE_URI"))
    except LakeConfigError:
        return
    run = registry.latest(lake, "t4")
    if run is None:
        log.info("T4: no model imported; the injection rule works alone")
        return
    gate = gates.text_gate(lake, "t4") if registry.uses_model(run) else None
    data = dataset.build()
    rows = data.train + data.test
    attacks = [r for r in rows if r.label]
    harmless = [r for r in rows if not r.label]
    for name, flags in (("rule", train.rule_flags), ("T4", gate)):
        if flags is None:
            log.info("T4 run %s lost on its test: not used", run.run_id)
            continue
        caught = sum(flags(r.text) for r in attacks)
        false = sum(flags(r.text) for r in harmless)
        log.info(
            "%s: caught %d of %d attacks, flagged %d of %d harmless texts",
            name, caught, len(attacks), false, len(harmless),
        )  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="redteam", description=__doc__)
    parser.add_argument("--corpus", type=Path, default=redteam.CORPUS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        cases = redteam.load(args.corpus)
    except redteam.CorpusError as e:
        log.error("%s", e)
        return 1
    report = redteam.run(cases)
    for owasp, (passed, total) in report.by_owasp().items():
        log.info("%s  %d/%d defenses held", owasp, passed, total)
    for result in report.failed:
        log.info(
            "FAILED %s (%s, %s): %s",
            result.case.id,
            result.case.owasp,
            result.case.atlas,
            result.detail,
        )
    log.info("%d cases, %d failed", len(report.results), len(report.failed))
    t4_line()
    return 1 if report.failed else 0
