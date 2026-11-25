"""Corrections and all-clears for alerts the engine sent (IU crime log and two-outlet news). IU's
own emergency alerts are relayed verbatim on the fast path and never touched here.

The ledger remembers the facts each alert went out with as a fingerprint claim
(facts/<incident>/<hash>), never the text. When an alerted incident's facts change, one correction
goes out per new set of facts; when the incident is over, one all-clear, after which the thread
gets nothing more. An all-clear needs a basis: the caller passes `closed` only when the official
record shows the case closed. Never an all-clear without one."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from campus_safety.alerts.ledger import Ledger, publish_key
from campus_safety.alerts.rules import Draft, Incident, Kind, render


@dataclass(frozen=True)
class Followup:
    incident_id: str
    kind: Kind
    draft: Draft


def fingerprint(incident: Incident) -> str:
    facts = [
        incident.incident_type,
        incident.location_text,
        incident.severity_tier,
        incident.injuries,
    ]
    return hashlib.sha256(json.dumps(facts).encode()).hexdigest()[:16]


def _facts_key(incident: Incident, fingerprint_: str = "") -> str:
    return f"facts/{incident.incident_id}/{fingerprint_}"


def record_facts(ledger: Ledger, incident: Incident, at: datetime) -> None:
    """Call when the alert is published: the facts it went out with."""
    ledger.claim(_facts_key(incident, fingerprint(incident)), at)


def followups(
    current: Iterable[tuple[Incident, bool]], ledger: Ledger, at: datetime
) -> list[Followup]:
    """`current`: each incident as it reads now, and whether the official record shows it closed."""
    found = []
    for incident, closed in current:
        iid = incident.incident_id
        if not ledger.claims(publish_key(iid, "alert")) or ledger.claims(
            publish_key(iid, "all_clear")
        ):
            continue
        if closed:
            if ledger.claim(publish_key(iid, "all_clear"), at):
                found.append(Followup(iid, "all_clear", render(incident, "all_clear")))
            continue
        if not ledger.claims(_facts_key(incident)):
            record_facts(ledger, incident, at)  # first sight: the facts it went out with
            continue
        if ledger.claim(_facts_key(incident, fingerprint(incident)), at):
            found.append(Followup(iid, "correction", render(incident, "correction")))
    return found
