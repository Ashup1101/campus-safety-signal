"""Subscribers and their addresses. Until Supabase (Phase 3) holds accounts, a local YAML file
(data/manual/subscribers.yaml, gitignored) lists test accounts only:

    subscribers:
      - subscriber_id: parent_mom
        role: parent
        zone_ids: [kirkwood_400, campus_core]
        channels: {email: parent@example.test}
        digest_only: false
        test_account: true

Addresses never leave the directory except to the channel that delivers to them.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from campus_safety.alerts.rules import Subscriber

SUBSCRIBERS = Path("data", "manual", "subscribers.yaml")
ROLES = ("student", "parent")
CHANNELS = ("email", "web_push", "iphone_push")


class DirectoryError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    subscriber: Subscriber
    addresses: dict[str, str]  # channel -> address (email, push endpoint id)


def load(path: Path = SUBSCRIBERS) -> list[Entry]:
    if not path.exists():
        return []
    entries = (yaml.safe_load(path.read_text()) or {}).get("subscribers", [])
    found = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise DirectoryError("each subscriber must be a mapping")
        sid, role = raw.get("subscriber_id"), raw.get("role")
        if not isinstance(sid, str) or not sid or role not in ROLES:
            raise DirectoryError("subscriber_id and a role of student|parent are required")
        zones = raw.get("zone_ids") or []
        channels = raw.get("channels") or {}
        if not isinstance(zones, list) or not isinstance(channels, dict):
            raise DirectoryError(f"{sid}: zone_ids must be a list and channels a mapping")
        if unknown := set(channels) - set(CHANNELS):
            raise DirectoryError(f"{sid}: unknown channels {sorted(unknown)}")
        found.append(
            Entry(
                Subscriber(
                    sid,
                    str(role),
                    tuple(str(z) for z in zones),
                    tuple(sorted(str(c) for c in channels)),
                    bool(raw.get("digest_only", False)),
                    bool(raw.get("test_account", False)),
                ),
                {str(c): str(a) for c, a in channels.items()},
            )
        )
    if len({e.subscriber.subscriber_id for e in found}) != len(found):
        raise DirectoryError("duplicate subscriber_id")
    return found
