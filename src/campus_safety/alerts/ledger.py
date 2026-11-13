"""Idempotency ledger: one delivery per (incident, kind, subscriber, channel), one publish per
(incident, kind). A claim is a write-once object, so two consumers racing on the same message
cannot both deliver: the lake's create-only semantics (If-None-Match on S3, link() on files)
are the lock. Objects hold timestamps only (latency measurement), never alert text.
"""

import json
from datetime import UTC, datetime
from typing import Protocol

from campus_safety.lake.storage import Lake, ObjectExistsError

PREFIX = "alerts"


class Ledger(Protocol):
    def claim(self, key: str, at: datetime, official_at: datetime | None = None) -> bool:
        """True when this call made the claim; False when it already existed."""
        ...

    def claims(self, prefix: str) -> list[str]: ...


class MemoryLedger:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, str | None]] = {}

    def claim(self, key: str, at: datetime, official_at: datetime | None = None) -> bool:
        if key in self.entries:
            return False
        self.entries[key] = _entry(at, official_at)
        return True

    def claims(self, prefix: str) -> list[str]:
        return sorted(k for k in self.entries if k.startswith(prefix))


class LakeLedger:
    def __init__(self, lake: Lake) -> None:
        self.lake = lake

    def claim(self, key: str, at: datetime, official_at: datetime | None = None) -> bool:
        try:
            self.lake.create(f"{PREFIX}/{key}", json.dumps(_entry(at, official_at)).encode())
        except ObjectExistsError:
            return False
        return True

    def claims(self, prefix: str) -> list[str]:
        start = f"{PREFIX}/"
        return [k.removeprefix(start) for k in self.lake.keys(f"{start}{prefix}")]


def _entry(at: datetime, official_at: datetime | None) -> dict[str, str | None]:
    return {
        "at": at.astimezone(UTC).isoformat(),
        "official_at": official_at.astimezone(UTC).isoformat() if official_at else None,
    }


def publish_key(incident_id: str, kind: str) -> str:
    return f"published/{incident_id}/{kind}"


def delivery_key(incident_id: str, kind: str, subscriber_id: str, channel: str) -> str:
    return f"delivered/{incident_id}/{kind}/{subscriber_id}/{channel}"
