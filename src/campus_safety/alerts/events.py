"""The incident.confirmed event (pubsub.md): schema-validated, no personal data.

Published once per incident and kind to SNS; every channel queue receives a copy. The event
carries ids, zones, severity and timing only; consumers render words from the incident fields
they fetch by id, never from the event.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from campus_safety.alerts.rules import Kind

SCHEMA_VERSION = 1
KINDS = ("alert", "correction", "all_clear")
SEVERITIES = ("high", "medium", "low", "service", "unclassified")


class EventError(ValueError):
    pass


@dataclass(frozen=True)
class IncidentConfirmed:
    incident_id: str
    kind: Kind
    severity: str
    zone_ids: tuple[str, ...]
    source: str  # official | news
    source_refs: tuple[str, ...]  # bronze keys or cluster ids, never text
    confirmed_at: datetime  # UTC
    official_at: datetime | None = None  # UTC, when the official source published
    version: int = SCHEMA_VERSION

    @property
    def dedupe_key(self) -> str:
        return f"{self.incident_id}|{self.kind}"

    def to_json(self) -> str:
        fields = asdict(self)
        fields["confirmed_at"] = self.confirmed_at.astimezone(UTC).isoformat()
        fields["official_at"] = (
            self.official_at.astimezone(UTC).isoformat() if self.official_at else None
        )
        fields["zone_ids"], fields["source_refs"] = list(self.zone_ids), list(self.source_refs)
        return json.dumps(fields, sort_keys=True)


def _stamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventError("timestamps must be ISO strings")
    try:
        at = datetime.fromisoformat(value)
    except ValueError as e:
        raise EventError("bad timestamp") from e
    if at.tzinfo is None:
        raise EventError("timestamps must carry a zone")
    return at.astimezone(UTC)


def parse(body: str) -> IncidentConfirmed:
    """Strict: unknown keys, missing keys, wrong types or values are all errors."""
    try:
        raw: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, TypeError) as e:
        raise EventError("event is not JSON") from e
    expected = {
        "incident_id", "kind", "severity", "zone_ids", "source", "source_refs",
        "confirmed_at", "official_at", "version",
    }  # fmt: skip
    if not isinstance(raw, dict) or set(raw) != expected:
        raise EventError("event keys do not match the schema")
    if raw["version"] != SCHEMA_VERSION:
        raise EventError("unsupported event version")
    if raw["kind"] not in KINDS or raw["severity"] not in SEVERITIES:
        raise EventError("bad kind or severity")
    if raw["source"] not in ("official", "news"):
        raise EventError("bad source")
    for name in ("zone_ids", "source_refs"):
        if not isinstance(raw[name], list) or not all(isinstance(v, str) for v in raw[name]):
            raise EventError(f"{name} must be a list of strings")
    if not isinstance(raw["incident_id"], str) or not raw["incident_id"]:
        raise EventError("incident_id required")
    confirmed = _stamp(raw["confirmed_at"])
    if confirmed is None:
        raise EventError("confirmed_at required")
    return IncidentConfirmed(
        raw["incident_id"],
        raw["kind"],
        raw["severity"],
        tuple(raw["zone_ids"]),
        raw["source"],
        tuple(raw["source_refs"]),
        confirmed,
        _stamp(raw["official_at"]),
    )
