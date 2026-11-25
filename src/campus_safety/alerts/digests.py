"""Daily and weekly digests: lower-level reports (rules route them to "digest") in one watch zone,
counted by plain kind and placed no finer than a street block. Templates only; an empty digest is
never sent."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from campus_safety.alerts.rules import CLOSING, Draft
from campus_safety.patterns.categories import plural

PLACES = 5


@dataclass(frozen=True)
class Item:
    category: str  # plain noun, e.g. "theft"
    place: str | None  # segment name; trimmed to the block
    occurred_at: datetime


def block_level(name: str) -> str:
    """'E Kirkwood Ave, 400 block (Grant to Dunn)' -> 'E Kirkwood Ave, 400 block'."""
    return name.split(" (", 1)[0]


def digest(
    period: str, zone_name: str, start: datetime, end: datetime, items: Sequence[Item]
) -> Draft | None:
    if not items:
        return None
    kinds = Counter(i.category for i in items)
    places = Counter(block_level(i.place) for i in items if i.place)
    span = f"{start:%a %b %-d} to {end:%a %b %-d}"
    reports = f"{len(items)} lower-level report{'s' if len(items) != 1 else ''}"
    lines = [
        f"{span}: {reports} near {zone_name}.",
        "By kind: " + ", ".join(f"{n} {plural(k, n)}" for k, n in kinds.most_common()),
    ]
    if places:
        lines.append("Where: " + "; ".join(f"{p} ({n})" for p, n in places.most_common(PLACES)))
    lines.append("Alerts are sent separately, when they happen.")
    lines.append(CLOSING)
    return Draft(f"{period.capitalize()} digest: {zone_name}", "\n".join(lines))
