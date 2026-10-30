"""Training pairs for T3-lite from the IU crime log in bronze.

Each incident the rules parser read gives (source text, target JSON); pages it could not read,
which include arrest logs, media logs, and empty archive pages, give none. Pairs are deduplicated
by source text and screened by Presidio for people's names. Splits are by date reported: test is
the last year, validation the year before, train everything older; the latest 10% of each legacy
PDF layout is held out of train to measure robustness on noisy PDF text.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from campus_safety.iu_crime_log import backfill, silver
from campus_safety.iu_crime_log.legacy import parse_legacy_pdf
from campus_safety.iu_crime_log.parse import CrimeLog, ParseError, parse_crime_log
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake
from campus_safety.t3.schema import target

SPLITS = ("train", "validation", "test", "legacy_holdout")
HOLDOUT_SHARE = 0.10


@dataclass(frozen=True)
class Pair:
    pair_id: str  # first 16 hex of sha256(source)
    dataset: str
    source_ref: str
    layout: str  # html | pdf_report | pdf_cad
    date_reported: str
    source: str
    target: dict[str, object]


def _parse(manifest: bronze.Manifest, body: bytes) -> CrimeLog:
    if manifest.key.endswith(".pdf.gz"):
        return parse_legacy_pdf(body)
    return parse_crime_log(body.decode("utf-8", errors="replace"))


def _layout(manifest: bronze.Manifest, source: str) -> str:
    if not manifest.key.endswith(".pdf.gz"):
        return "html"
    return "pdf_cad" if "Location :" in source else "pdf_report"


def collect(lake: Lake, has_person: Callable[[str], bool]) -> tuple[list[Pair], Counter[str]]:
    counts: Counter[str] = Counter()
    pairs: dict[str, Pair] = {}
    manifests = sorted(
        (m for ds in (silver.SOURCE, backfill.SOURCE) for m in bronze.manifests(lake, ds)),
        key=lambda m: (m.observed_at, m.key),
    )
    for manifest in manifests:
        try:
            log = _parse(manifest, bronze.read(lake, manifest))
        except ParseError:
            counts["snapshots_unparsed"] += 1
            continue
        counts["snapshots_parsed"] += 1
        for incident, source in zip(log.incidents, log.sources, strict=True):
            counts["incidents_seen"] += 1
            pair_id = hashlib.sha256(source.encode()).hexdigest()[:16]
            if pair_id in pairs:
                counts["duplicates"] += 1
                continue
            if has_person(source):
                counts["dropped_person"] += 1
                continue
            pairs[pair_id] = Pair(
                pair_id=pair_id,
                dataset=manifest.source,
                source_ref=manifest.key,
                layout=_layout(manifest, source),
                date_reported=incident.date_reported.isoformat(),
                source=source,
                target=target(incident),
            )
    return sorted(pairs.values(), key=lambda p: (p.date_reported, p.pair_id)), counts


def split(pairs: Iterable[Pair]) -> dict[str, list[Pair]]:
    pairs = list(pairs)
    last = max(date.fromisoformat(p.date_reported) for p in pairs)
    test_after, validation_after = last - timedelta(days=365), last - timedelta(days=730)
    held: set[str] = set()
    for layout in ("pdf_report", "pdf_cad"):
        legacy = [p for p in pairs if p.layout == layout]  # already in date order
        held |= {p.pair_id for p in legacy[len(legacy) - round(len(legacy) * HOLDOUT_SHARE) :]}
    splits: dict[str, list[Pair]] = {name: [] for name in SPLITS}
    for pair in pairs:
        reported = date.fromisoformat(pair.date_reported)
        if reported > test_after:
            splits["test"].append(pair)
        elif reported > validation_after:
            splits["validation"].append(pair)
        elif pair.pair_id in held:
            splits["legacy_holdout"].append(pair)
        else:
            splits["train"].append(pair)
    return splits


def write(splits: dict[str, list[Pair]], counts: Counter[str], out: Path) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, object] = {"counts": dict(sorted(counts.items())), "splits": {}}
    for name, rows in splits.items():
        with (out / f"{name}.jsonl").open("w") as file:
            for pair in rows:
                file.write(json.dumps(asdict(pair), ensure_ascii=False) + "\n")
        stats["splits"][name] = {  # type: ignore[index]
            "rows": len(rows),
            "by_layout": dict(sorted(Counter(p.layout for p in rows).items())),
            "date_range": [rows[0].date_reported, rows[-1].date_reported] if rows else None,
        }
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats
