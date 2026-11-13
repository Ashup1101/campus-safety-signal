"""Staging rows for news: items, extractions, and cross-outlet clusters.

Only relevant items keep their text, and that text is stored after Presidio name redaction and
descriptor stripping. Irrelevant items keep their id, link and time only. Clusters are built
over every unique item in bronze, so they are staged once per transform, not per page.
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from campus_safety.collectors.sources import SOURCES
from campus_safety.iu_crime_log.classify import location_type
from campus_safety.lake import bronze
from campus_safety.lake.parquet import Columns
from campus_safety.lake.storage import Lake
from campus_safety.news.dedupe import Candidate, clusters
from campus_safety.news.extract import SEVERITY, Extraction, Extractor
from campus_safety.news.items import Item, ItemsLayoutError, items
from campus_safety.news.screen import screen
from campus_safety.official.descriptors import strip_descriptors

log = logging.getLogger("news")

NEWS_SOURCES = tuple(s.name for s in SOURCES)
NAME_MARKER = "[name removed]"
Redact = Callable[[str], str]

ITEMS: Columns = (
    ("dataset", "VARCHAR"),  # bronze source: the outlet
    ("tier", "INTEGER"),
    ("item_id", "VARCHAR"),
    ("url", "VARCHAR"),
    ("title", "VARCHAR"),  # null unless relevant; redacted
    ("summary", "VARCHAR"),
    ("published_at", "TIMESTAMP"),  # UTC
    ("observed_at", "TIMESTAMP"),  # UTC, first page that listed it
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
    ("relevant", "BOOLEAN"),
    ("injection_suspected", "BOOLEAN"),
)
EXTRACTIONS: Columns = (
    ("item_id", "VARCHAR"),
    ("extractor", "VARCHAR"),  # rules | llm
    ("incident_type", "VARCHAR"),
    ("occurred_date", "DATE"),
    ("occurred_time", "VARCHAR"),
    ("location_text", "VARCHAR"),
    ("injuries", "INTEGER"),
    ("deaths", "INTEGER"),
    ("weapon_involved", "BOOLEAN"),
    ("iu_related", "BOOLEAN"),
    ("grounded", "BOOLEAN"),
)
CLUSTERS: Columns = (
    ("cluster_id", "VARCHAR"),
    ("incident_type", "VARCHAR"),
    ("severity", "VARCHAR"),
    ("sensitive", "BOOLEAN"),
    ("occurred_date", "DATE"),
    ("occurred_time", "VARCHAR"),
    ("location_text", "VARCHAR"),
    ("location_type", "VARCHAR"),
    ("injuries", "INTEGER"),
    ("deaths", "INTEGER"),
    ("weapon_involved", "BOOLEAN"),
    ("iu_related", "BOOLEAN"),
    ("outlets", "INTEGER"),  # distinct tier 2 outlets
    ("official", "BOOLEAN"),  # a tier 1 source is in the cluster
    ("confirmed", "BOOLEAN"),  # official or >= 2 outlets (alerts.md)
    ("item_count", "INTEGER"),
    ("first_published_at", "TIMESTAMP"),
    ("first_item_id", "VARCHAR"),
    ("source_ref", "VARCHAR"),  # bronze key behind the first item
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
    ("injection_suspected", "BOOLEAN"),  # any item in the cluster was flagged
)
CLUSTER_ITEMS: Columns = (
    ("cluster_id", "VARCHAR"),
    ("item_id", "VARCHAR"),
    ("dataset", "VARCHAR"),
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
    ("published_at", "TIMESTAMP"),
)
TABLES: dict[str, Columns] = {
    "news_items": ITEMS,
    "news_extractions": EXTRACTIONS,
    "news_clusters": CLUSTERS,
    "news_cluster_items": CLUSTER_ITEMS,
}


@dataclass
class NewsSummary:
    pages: int = 0
    layout_errors: int = 0
    items: int = 0  # unique
    relevant: int = 0
    injection_suspected: int = 0
    incidents: int = 0  # items the chosen extraction calls an incident
    clusters: int = 0
    confirmed: int = 0
    ungrounded: int = 0  # model answers that named a place not in the item


def presidio_redactor() -> Redact:
    """Names found by Presidio become NAME_MARKER (privacy.md: no names beyond bronze)."""
    from campus_safety.t3.privacy import PersonScreen

    screen_ = PersonScreen()

    def redact(text: str) -> str:
        for name in sorted(set(screen_.names(text)), key=len, reverse=True):
            text = text.replace(name, NAME_MARKER)
        return text

    return redact


def stored_text(text: str, redact: Redact) -> str:
    return strip_descriptors(redact(text))


def unique_items(lake: Lake, summary: NewsSummary) -> list[Item]:
    """Every item in bronze, keeping the earliest page that listed each one."""
    first: dict[str, Item] = {}
    for source in NEWS_SOURCES:
        for manifest in bronze.manifests(lake, source):
            summary.pages += 1
            try:
                found = items(manifest, bronze.read(lake, manifest))
            except ItemsLayoutError:
                summary.layout_errors += 1
                continue
            for item in found:
                known = first.get(item.item_id)
                if known is None or item.observed_at < known.observed_at:
                    first[item.item_id] = item
    summary.items = len(first)
    return sorted(first.values(), key=lambda i: (i.observed_at, i.item_id))


def _utc(at: datetime | None) -> datetime | None:
    return at.astimezone(UTC).replace(tzinfo=None) if at else None


def _choose(found: dict[str, Extraction | None]) -> Extraction | None:
    """The model's answer when it is grounded, else the rules'."""
    llm = found.get("llm")
    if llm is not None and llm.grounded:
        return llm
    return found.get("rules")


def stage(
    found: Iterable[Item],
    extractors: list[Extractor],
    redact: Redact,
    now: datetime,
    summary: NewsSummary | None = None,
) -> tuple[dict[str, list[tuple[object, ...]]], NewsSummary]:
    summary = summary or NewsSummary()
    rows: dict[str, list[tuple[object, ...]]] = {name: [] for name in TABLES}
    candidates: list[Candidate] = []
    flagged: set[str] = set()
    ingested = _utc(now)
    for item in found:
        screened = screen(item.text)
        title = summary_ = None
        if screened.relevant:
            summary.relevant += 1
            title = stored_text(screen(item.title).text, redact)
            summary_ = stored_text(screen(item.summary).text, redact) if item.summary else ""
        if screened.injection_suspected:
            summary.injection_suspected += 1
            flagged.add(item.item_id)
        rows["news_items"].append(
            (
                item.source,
                item.tier,
                item.item_id,
                item.url,
                title,
                summary_,
                _utc(item.published_at),
                _utc(item.observed_at),
                item.source_ref,
                item.run_id,
                ingested,
                screened.relevant,
                screened.injection_suspected,
            )
        )
        if not screened.relevant:
            continue
        answers: dict[str, Extraction | None] = {}
        for extractor in extractors:
            extraction = extractor.extract(screened.text, item.published_at)
            answers[extractor.name] = extraction
            if extraction is None:
                continue
            if not extraction.grounded:
                summary.ungrounded += 1
            rows["news_extractions"].append(
                (
                    item.item_id,
                    extractor.name,
                    extraction.incident_type,
                    extraction.occurred_date,
                    extraction.occurred_time,
                    extraction.location_text,
                    extraction.injuries,
                    extraction.deaths,
                    extraction.weapon_involved,
                    extraction.iu_related,
                    extraction.grounded,
                )
            )
        chosen = _choose(answers)
        if chosen is not None and chosen.is_incident:
            summary.incidents += 1
            candidates.append(Candidate(item, chosen))

    for cluster in clusters(candidates):
        summary.clusters += 1
        summary.confirmed += cluster.confirmed
        first = cluster.first
        location = cluster.location_text
        rows["news_clusters"].append(
            (
                cluster.cluster_id,
                cluster.incident_type,
                SEVERITY[cluster.incident_type].value,
                cluster.incident_type
                in {
                    c.extraction.incident_type
                    for c in cluster.candidates
                    if c.extraction.is_sensitive
                },
                cluster.occurred_date,
                cluster.occurred_time,
                location,
                location_type(location.upper()).value if location else "unknown",
                cluster.injuries,
                cluster.deaths,
                cluster.weapon_involved,
                cluster.iu_related,
                cluster.outlets,
                cluster.official,
                cluster.confirmed,
                len(cluster.candidates),
                _utc(cluster.first_published_at),
                first.item.item_id,
                first.item.source_ref,
                first.item.run_id,
                ingested,
                any(c.item.item_id in flagged for c in cluster.candidates),
            )
        )
        rows["news_cluster_items"].extend(
            (
                cluster.cluster_id,
                c.item.item_id,
                c.item.source,
                c.item.source_ref,
                c.item.run_id,
                ingested,
                _utc(c.item.published_at),
            )
            for c in cluster.candidates
        )
    return rows, summary
