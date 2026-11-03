"""SQLite for demo accounts, links, watch zones, alerts, deliveries, and activity levels.

Live location and "parent viewing" presence never come here: they live in the hub's memory only.
Alert text is stored with suspect descriptions removed; only the live relay carries it verbatim.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from campus_safety.official.alerts import OfficialAlert
from campus_safety.official.descriptors import strip_descriptors

Role = Literal["student", "parent", "console"]

SCHEMA = """
create table if not exists accounts (
    id text primary key,
    role text not null check (role in ('student', 'parent', 'console')),
    display_name text not null,
    is_test integer not null check (is_test in (0, 1))
);
create table if not exists links (
    parent_id text not null references accounts (id),
    student_id text not null references accounts (id),
    parent_label text not null,
    primary key (parent_id, student_id)
);
create table if not exists zones (
    id integer primary key,
    account_id text not null references accounts (id),
    name text not null,
    lat real not null,
    lon real not null,
    radius_m integer not null
);
create table if not exists alerts (
    id text primary key,
    source text not null,
    kind text not null,
    status text not null,
    verification text not null,
    test_only integer not null,
    official_at text,
    received_at text not null,
    stored_text text not null,
    link text
);
create table if not exists deliveries (
    alert_id text not null references alerts (id),
    account_id text not null references accounts (id),
    client text not null check (client in ('web', 'ios')),
    shown_at text not null,
    primary key (alert_id, account_id, client)
);
create table if not exists activity (
    segment_id text not null,
    time_window text not null,
    level text not null check (level in ('quiet', 'elevated', 'high')),
    reason text not null,
    incidents integer not null,
    serious integer not null,
    primary key (segment_id, time_window)
);
"""


@dataclass(frozen=True)
class Account:
    id: str
    role: Role
    display_name: str
    is_test: bool


@dataclass(frozen=True)
class Zone:
    name: str
    lat: float
    lon: float
    radius_m: int


@dataclass(frozen=True)
class Activity:
    segment_id: str
    window: str
    level: str
    reason: str
    incidents: int
    serious: int


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # One event loop thread uses it; the flag only allows creating it elsewhere.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("pragma foreign_keys = on")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def add_account(self, account: Account) -> None:
        with self._db:
            self._db.execute(
                "insert or replace into accounts values (?, ?, ?, ?)",
                (account.id, account.role, account.display_name, int(account.is_test)),
            )

    def link(self, parent_id: str, student_id: str, label: str) -> None:
        with self._db:
            self._db.execute(
                "insert or replace into links values (?, ?, ?)", (parent_id, student_id, label)
            )

    def add_zone(self, account_id: str, zone: Zone) -> None:
        with self._db:
            self._db.execute(
                "insert into zones (account_id, name, lat, lon, radius_m) values (?, ?, ?, ?, ?)",
                (account_id, zone.name, zone.lat, zone.lon, zone.radius_m),
            )

    def accounts(self) -> list[Account]:
        rows = self._db.execute("select * from accounts order by role, display_name").fetchall()
        return [Account(r[0], r[1], r[2], bool(r[3])) for r in rows]

    def account(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts() if a.id == account_id), None)

    def students_of(self, parent_id: str) -> list[str]:
        rows = self._db.execute(
            "select student_id from links where parent_id = ? order by student_id", (parent_id,)
        )
        return [r[0] for r in rows]

    def parents_of(self, student_id: str) -> dict[str, str]:
        """Linked parent id -> the label the student knows them by ("Mom")."""
        rows = self._db.execute(
            "select parent_id, parent_label from links where student_id = ?", (student_id,)
        )
        return dict(rows.fetchall())

    def zones(self, account_id: str) -> list[Zone]:
        rows = self._db.execute(
            "select name, lat, lon, radius_m from zones where account_id = ? order by id",
            (account_id,),
        )
        return [Zone(*r) for r in rows]

    def add_alert(self, alert_id: str, alert: OfficialAlert, received_at: datetime) -> None:
        with self._db:
            self._db.execute(
                "insert into alerts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alert_id,
                    alert.source,
                    alert.kind,
                    alert.status,
                    alert.verification,
                    int(alert.test_only),
                    alert.official_at.isoformat() if alert.official_at else None,
                    received_at.isoformat(),
                    strip_descriptors(alert.text),
                    alert.link,
                ),
            )

    def alerts(self, include_test: bool, limit: int = 50) -> list[dict[str, object]]:
        rows = self._db.execute(
            "select id, source, kind, status, verification, official_at, received_at,"
            " stored_text, link from alerts where test_only = 0 or ?"
            " order by received_at desc limit ?",
            (int(include_test), limit),
        )
        keys = ["id", "source", "kind", "status", "verification", "official_at"]
        keys += ["received_at", "text", "link"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def delivered(self, alert_id: str, account_id: str, client: str, shown_at: datetime) -> None:
        with self._db:
            self._db.execute(
                "insert or ignore into deliveries values (?, ?, ?, ?)",
                (alert_id, account_id, client, shown_at.isoformat()),
            )

    def latency(self, limit: int = 20) -> list[dict[str, object]]:
        """Per alert: official time, server received, first shown on web and on iPhone."""
        rows = self._db.execute(
            """
            select a.id, a.kind, a.verification, a.status, a.official_at, a.received_at,
                   min(case when d.client = 'web' then d.shown_at end),
                   min(case when d.client = 'ios' then d.shown_at end)
            from alerts a left join deliveries d on d.alert_id = a.id
            group by a.id order by a.received_at desc limit ?
            """,
            (limit,),
        )
        keys = ["id", "kind", "verification", "status", "official_at", "received_at"]
        keys += ["web_at", "ios_at"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def replace_activity(self, rows: list[Activity]) -> None:
        with self._db:
            self._db.execute("delete from activity")
            self._db.executemany(
                "insert into activity values (?, ?, ?, ?, ?, ?)",
                [(r.segment_id, r.window, r.level, r.reason, r.incidents, r.serious) for r in rows],
            )

    def activity(self) -> list[Activity]:
        rows = self._db.execute("select * from activity order by segment_id, time_window")
        return [Activity(*r) for r in rows]
