"""Demo accounts (all test accounts), links, watch zones, and activity levels."""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from campus_safety import events
from demo_server import activity
from demo_server.store import Account, Store, Zone

ROOT = Path(__file__).resolve().parents[3]

ACCOUNTS = [
    Account("student_sam", "student", "Sam", True),
    Account("student_alex", "student", "Alex", True),
    Account("parent_mom", "parent", "Mom", True),
    Account("parent_dad", "parent", "Dad", True),
    Account("console", "console", "IUPD demo console", True),
]
LINKS = [("parent_mom", "student_sam", "Mom"), ("parent_dad", "student_alex", "Dad")]
ZONES = {
    "parent_mom": [
        Zone("Kirkwood Avenue", 39.16657, -86.5305, 350),
        Zone("Campus core", 39.16850, -86.5215, 700),
    ],
    "parent_dad": [Zone("Campus core", 39.16850, -86.5215, 700)],
}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / "data" / "demo"
    warehouse: Path = ROOT / "data" / "warehouse" / "warehouse.duckdb"
    manual: Path = ROOT / "data" / "manual" / "demo_incidents.yaml"
    tiles: Path = ROOT / "data" / "demo" / "tiles"
    gaps: Path = ROOT / "configs" / "gaps.yaml"
    rag_index: Path = ROOT / "data" / "rag" / "index.duckdb"
    lake_uri: str = (ROOT / "data" / "lake").as_uri()
    live_feed: bool = False
    replay_speed: float = 60.0
    # Postgres (Supabase) when set; a secret, so never shown in repr or logs.
    database_url: str | None = field(
        default_factory=lambda: os.environ.get("DEMO_DATABASE_URL") or None, repr=False
    )

    # Sign-in: "demo" (own links to the in-app mailbox) or "supabase" (Supabase Auth magic links).
    auth_mode: str = field(default_factory=lambda: os.environ.get("AUTH_MODE", "demo") or "demo")
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", ""))
    # Messages: "mailbox" (the in-app mailbox only) or "smtp" (also real email; SMTP_* settings).
    email_mode: str = field(
        default_factory=lambda: os.environ.get("EMAIL_MODE", "mailbox") or "mailbox"
    )
    # Push to closed apps: "off" (default) or "expo" (Expo's service; EXPO_ACCESS_TOKEN optional).
    push_mode: str = field(default_factory=lambda: os.environ.get("PUSH_MODE", "off") or "off")
    console_allowlist: Path = ROOT / "configs" / "console_allowlist.yaml"
    supabase_service_key: str | None = field(  # admin API (delete account); a secret
        default_factory=lambda: os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or None, repr=False
    )
    supabase_jwt_secret: str | None = field(
        default_factory=lambda: os.environ.get("SUPABASE_JWT_SECRET") or None, repr=False
    )

    @property
    def db(self) -> Path | str:
        return self.database_url or self.data_dir / "demo.sqlite3"


def console_emails(path: Path) -> frozenset[str]:
    """Lower-cased addresses allowed to the console (AUTH_MODE=supabase); none without the file."""
    if not path.is_file():
        return frozenset()
    data = yaml.safe_load(path.read_text()) or {}
    return frozenset(str(e).strip().lower() for e in data.get("emails") or [] if str(e).strip())


def seed(
    store: Store,
    settings: Settings,
    now: datetime | None = None,
    geojson: dict[str, Any] | None = None,
) -> None:
    if not store.accounts():
        for account in ACCOUNTS:
            store.add_account(account)
        for parent, student, label in LINKS:
            store.link(parent, student, label)
        for account_id, zones in ZONES.items():
            for zone in zones:
                store.add_zone(account_id, zone)
    geojson = geojson or activity.load_segments(settings.warehouse)
    found = activity.segments(geojson)
    manual = activity.manual_incidents(settings.manual)
    if activity.is_generated(geojson):
        incidents = activity.point_incidents(settings.warehouse)
        incidents += activity.translate(manual, activity.load_geojson(), geojson)
    else:
        incidents = activity.warehouse_incidents(settings.warehouse, found) + manual
    current = events.local(now or datetime.now(events.LOCAL))
    rows = activity.levels([s.id for s in found], incidents, current, events.event_nights())
    if activity.is_generated(geojson):
        rows += activity.tonight_rows(settings.warehouse, geojson, events.night_of(current))
    store.replace_activity(rows)
    log.info("activity from %d incidents on %d segments", len(incidents), len(found))
