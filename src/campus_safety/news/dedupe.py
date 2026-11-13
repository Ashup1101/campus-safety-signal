"""Cross-outlet clustering: the same incident reported by several outlets becomes one cluster.

Two items match when they have the same incident type, happened within a day of each other,
and name the same place (or at least one of them names none and both were published within a
day). Tier 2 confirmation (alerts.md) needs two distinct outlets; an official item confirms
alone. Field values are merged official-first, then earliest-first.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from campus_safety.events import LOCAL
from campus_safety.news.extract import Extraction
from campus_safety.news.items import Item

STOPWORDS = frozenset(
    [
        "block",
        "of",
        "the",
        "a",
        "an",
        "at",
        "on",
        "near",
        "along",
        "in",
        "and",
        "st",
        "street",
        "ave",
        "avenue",
        "rd",
        "road",
        "dr",
        "drive",
        "blvd",
        "boulevard",
        "ln",
        "lane",
        "ct",
        "court",
        "pl",
        "place",
        "n",
        "s",
        "e",
        "w",
        "north",
        "south",
        "east",
        "west",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")
SAME_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Candidate:
    item: Item
    extraction: Extraction

    @property
    def day(self) -> date | None:
        if self.extraction.occurred_date:
            return self.extraction.occurred_date
        at = self.item.published_at
        return at.astimezone(LOCAL).date() if at else None


@dataclass
class Cluster:
    cluster_id: str
    candidates: list[Candidate] = field(default_factory=list)

    def _ordered(self) -> list[Candidate]:
        far = datetime.max.replace(tzinfo=LOCAL)
        return sorted(self.candidates, key=lambda c: (c.item.tier, c.item.published_at or far))

    def _first(self, name: str) -> object:
        return next(
            (
                getattr(c.extraction, name)
                for c in self._ordered()
                if getattr(c.extraction, name) is not None
            ),
            None,
        )

    @property
    def incident_type(self) -> str:
        return str(self.candidates[0].extraction.incident_type)

    @property
    def occurred_date(self) -> date | None:
        return min((c.day for c in self.candidates if c.day), default=None)

    @property
    def occurred_time(self) -> str | None:
        value = self._first("occurred_time")
        return str(value) if value is not None else None

    @property
    def location_text(self) -> str | None:
        value = self._first("location_text")
        return str(value) if value is not None else None

    @property
    def injuries(self) -> int | None:
        return max(
            (c.extraction.injuries for c in self.candidates if c.extraction.injuries is not None),
            default=None,
        )

    @property
    def deaths(self) -> int | None:
        return max(
            (c.extraction.deaths for c in self.candidates if c.extraction.deaths is not None),
            default=None,
        )

    @property
    def weapon_involved(self) -> bool | None:
        value = self._first("weapon_involved")
        return bool(value) if value is not None else None

    @property
    def iu_related(self) -> bool:
        return any(c.extraction.iu_related for c in self.candidates)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({c.item.source for c in self.candidates}))

    @property
    def outlets(self) -> int:
        """Distinct tier 2 outlets."""
        return len({c.item.source for c in self.candidates if c.item.tier == 2})

    @property
    def official(self) -> bool:
        return any(c.item.tier == 1 for c in self.candidates)

    @property
    def confirmed(self) -> bool:
        return self.official or self.outlets >= 2

    @property
    def first(self) -> Candidate:
        return (
            self._ordered()[0]
            if self.official
            else min(
                self.candidates,
                key=lambda c: c.item.published_at or datetime.max.replace(tzinfo=LOCAL),
            )
        )

    @property
    def first_published_at(self) -> datetime | None:
        return min(
            (c.item.published_at for c in self.candidates if c.item.published_at), default=None
        )


def location_tokens(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    return frozenset(t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS)


def _published_close(a: Item, b: Item) -> bool:
    if a.published_at is None or b.published_at is None:
        return False
    return abs(a.published_at - b.published_at) <= SAME_DAY


def same_incident(a: Candidate, b: Candidate) -> bool:
    if a.extraction.incident_type != b.extraction.incident_type:
        return False
    if a.day and b.day and abs(a.day - b.day) > SAME_DAY:
        return False
    tokens_a, tokens_b = (
        location_tokens(a.extraction.location_text),
        location_tokens(b.extraction.location_text),
    )
    if tokens_a and tokens_b:
        return bool(tokens_a & tokens_b)
    return _published_close(a.item, b.item)


def clusters(candidates: list[Candidate]) -> list[Cluster]:
    """Greedy, oldest first; the cluster id is derived from its oldest item, so it is stable
    as long as that item stays in bronze."""
    far = datetime.max.replace(tzinfo=LOCAL)
    found: list[Cluster] = []
    for candidate in sorted(candidates, key=lambda c: (c.item.published_at or far, c.item.item_id)):
        if not candidate.extraction.is_incident:
            continue
        for cluster in found:
            if any(same_incident(candidate, other) for other in cluster.candidates):
                cluster.candidates.append(candidate)
                break
        else:
            digest = hashlib.sha256(f"cluster|{candidate.item.item_id}".encode()).hexdigest()[:16]
            found.append(Cluster(digest, [candidate]))
    return found
