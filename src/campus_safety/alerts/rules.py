"""Fixed rules decide whether an incident alerts and whom; templates draft the words.

alerts.md: tier 1 official needs one source, tier 2 news needs two independent outlets, tier 3
never; sensitive offenses never alert; low severity goes to digests only; every alert gets a
correction or an all-clear; the closing line is static. No names, no victim details, no
article text: templates use structured fields only.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from campus_safety.patterns.categories import category

# Spelled out here (not campus_safety.events) so the Lambda package needs no PyYAML.
LOCAL = ZoneInfo("America/Indiana/Indianapolis")

Kind = Literal["alert", "correction", "all_clear"]
Route = Literal["alert", "digest", "none"]
CLOSING = "Follow official IU instructions; call 911 in an emergency."


@dataclass(frozen=True)
class Incident:
    """What the engine needs from gold.incidents_real / silver.news_incidents."""

    incident_id: str
    source: str  # official | news | synthetic
    confirmed: bool  # official: always; news: >= 2 outlets
    severity_tier: str | None
    incident_type: str
    location_text: str | None
    zone_ids: tuple[str, ...]
    occurred_at: datetime | None  # local wall time
    is_sensitive: bool
    injuries: int | None = None
    official_at: datetime | None = None  # when the official source published (latency)


@dataclass(frozen=True)
class Subscriber:
    subscriber_id: str
    role: str  # student | parent
    zone_ids: tuple[str, ...]
    channels: tuple[str, ...]  # email | web_push | iphone_push
    digest_only: bool = False
    test_account: bool = False


@dataclass(frozen=True)
class Decision:
    route: Route
    severity: str
    reason: str  # one short, logged line (field names only)


def decide(incident: Incident) -> Decision:
    if incident.is_sensitive:
        return Decision("none", "n/a", "sensitive offense")
    if incident.source == "synthetic":
        return Decision("none", "n/a", "synthetic row")
    if not incident.confirmed:
        return Decision("none", "n/a", "unconfirmed news")
    tier = incident.severity_tier or "unclassified"
    if tier in ("high", "medium"):
        return Decision("alert", tier, f"{incident.source} {tier}")
    return Decision("digest", tier, f"{incident.source} {tier}: digest only")


def recipients(incident: Incident, subscribers: Iterable[Subscriber]) -> list[Subscriber]:
    """Subscribers watching any of the incident's zones; digest-only subscribers never get
    live alerts. An incident without a zone reaches nobody (never a campus-wide blast)."""
    if not incident.zone_ids:
        return []
    zones = set(incident.zone_ids)
    return [s for s in subscribers if not s.digest_only and zones & set(s.zone_ids)]


@dataclass(frozen=True)
class Draft:
    title: str
    body: str


def _when(at: datetime | None) -> str:
    if at is None:
        return "time not yet confirmed"
    local = at.astimezone(LOCAL) if at.tzinfo else at
    return local.strftime("%a %b %-d, %-I:%M %p").replace(" 0", " ")


def _what(incident: Incident) -> str:
    kind = category(incident.incident_type)
    return kind[0].upper() + kind[1:]


def render(incident: Incident, kind: Kind = "alert") -> Draft:
    what = _what(incident)
    where = f" near {incident.location_text}" if incident.location_text else ""
    source = "IU/official source" if incident.source == "official" else "two local news outlets"
    if kind == "correction":
        title = f"Correction: {what.lower()}{where}"
        body = f"Details of the earlier alert have changed ({source}). {CLOSING}"
    elif kind == "all_clear":
        title = f"All clear: {what.lower()}{where}"
        body = f"The {source} reports this incident is over. {CLOSING}"
    else:
        title = f"{what}{where}"
        hurt = f" {incident.injuries} injured." if incident.injuries else ""
        body = f"{what}{where}, {_when(incident.occurred_at)} ({source}).{hurt} {CLOSING}"
    return Draft(title, body)
