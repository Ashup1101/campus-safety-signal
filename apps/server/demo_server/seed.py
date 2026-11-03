"""Demo accounts (all test accounts), links, watch zones, and activity levels."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    lake_uri: str = (ROOT / "data" / "lake").as_uri()
    live_feed: bool = False
    replay_speed: float = 60.0

    @property
    def db(self) -> Path:
        return self.data_dir / "demo.sqlite3"


def seed(store: Store, settings: Settings, now: datetime | None = None) -> None:
    if not store.accounts():
        for account in ACCOUNTS:
            store.add_account(account)
        for parent, student, label in LINKS:
            store.link(parent, student, label)
        for account_id, zones in ZONES.items():
            for zone in zones:
                store.add_zone(account_id, zone)
    found = activity.segments(activity.load_geojson())
    incidents = activity.warehouse_incidents(settings.warehouse, found)
    incidents += activity.manual_incidents(settings.manual)
    current = events.local(now or datetime.now(events.LOCAL))
    rows = activity.levels([s.id for s in found], incidents, current, events.event_nights())
    store.replace_activity(rows)
    log.info("activity from %d incidents on %d segments", len(incidents), len(found))
