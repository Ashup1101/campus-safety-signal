"""redteam: run the corpus with a worst-case (fully obedient) model and print pass counts per
OWASP id. Exit 1 if any defense fails. No network, no paid model, ids and verdicts only."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from campus_safety.security import redteam

log = logging.getLogger("redteam")


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
    return 1 if report.failed else 0
