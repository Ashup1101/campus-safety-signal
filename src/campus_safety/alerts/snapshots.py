"""Small JSON objects in the lake that consumers read with boto3 alone (no duckdb in Lambda):
the structured incident fields an alert is rendered from, and the subscriber directory.
Both hold fields only: no article text, no names.
"""

import json
from dataclasses import asdict
from datetime import datetime

from campus_safety.alerts.directory import Entry
from campus_safety.alerts.rules import Incident, Subscriber
from campus_safety.lake.storage import Lake

INCIDENTS = "alerts/incidents"
DIRECTORY = "alerts/subscribers.json"


def _stamp(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def store_incident(lake: Lake, incident: Incident) -> None:
    fields = asdict(incident)
    fields["occurred_at"] = _stamp(incident.occurred_at)
    fields["official_at"] = _stamp(incident.official_at)
    fields["zone_ids"] = list(incident.zone_ids)
    lake.put(
        f"{INCIDENTS}/{incident.incident_id}.json", json.dumps(fields, sort_keys=True).encode()
    )


def load_incident(lake: Lake, incident_id: str) -> Incident | None:
    try:
        fields = json.loads(lake.get(f"{INCIDENTS}/{incident_id}.json"))
    except (FileNotFoundError, KeyError):
        return None
    except Exception as e:  # boto3 NoSuchKey surfaces as a ClientError subclass
        if type(e).__name__ not in ("NoSuchKey", "ClientError"):
            raise
        return None
    return Incident(
        fields["incident_id"],
        fields["source"],
        bool(fields["confirmed"]),
        fields["severity_tier"],
        fields["incident_type"],
        fields["location_text"],
        tuple(fields["zone_ids"]),
        _parse(fields["occurred_at"]),
        bool(fields["is_sensitive"]),
        fields.get("injuries"),
        _parse(fields.get("official_at")),
    )


def store_directory(lake: Lake, entries: list[Entry]) -> None:
    payload = [{"subscriber": asdict(e.subscriber), "addresses": e.addresses} for e in entries]
    lake.put(DIRECTORY, json.dumps(payload, sort_keys=True).encode())


def load_directory(lake: Lake) -> list[Entry]:
    try:
        payload = json.loads(lake.get(DIRECTORY))
    except (FileNotFoundError, KeyError):
        return []
    except Exception as e:
        if type(e).__name__ not in ("NoSuchKey", "ClientError"):
            raise
        return []
    return [
        Entry(
            Subscriber(
                s["subscriber_id"],
                s["role"],
                tuple(s["zone_ids"]),
                tuple(s["channels"]),
                bool(s["digest_only"]),
                bool(s["test_account"]),
            ),
            dict(raw["addresses"]),
        )
        for raw in payload
        for s in (raw["subscriber"],)
    ]
