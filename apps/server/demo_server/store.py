"""SQLite for demo accounts, links, watch zones, alerts, deliveries, and activity levels.

Live location and "parent viewing" presence never come here: they live in the hub's memory only.
Alert text is stored with suspect descriptions removed; only the live relay carries it verbatim.
"""

import re
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Literal

from campus_safety.official.alerts import OfficialAlert
from campus_safety.official.descriptors import strip_descriptors
from demo_server import signing
from demo_server.db import Database, insert_ignore_sql, is_postgres_url, upsert_sql
from demo_server.threads import THREAD_GAP

LINK = upsert_sql("links", ("parent_id", "student_id", "parent_label"), ("parent_id", "student_id"))
CONSENT = upsert_sql(
    "consents",
    ("account_id", "kind", "version", "granted_at", "withdrawn_at"),
    ("account_id", "kind"),
)
Role = Literal["student", "parent", "console"]
INVITE_LIFETIME = timedelta(days=7)


def _locked[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """FastAPI runs sync handlers in a thread pool; one sqlite connection must serve one call at a
    time, or parallel lookups interleave and lose rows (spurious 401s and 404s). Postgres gives
    each thread its own pooled connection, so it needs no lock."""

    @wraps(method)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        store: Any = args[0]
        with store._lock:
            return method(*args, **kwargs)

    return call


MAILBOX = """create table if not exists mailbox (
    id integer primary key,
    account_id text not null references accounts (id),
    kind text not null check (
        kind in ('briefing', 'digest', 'alert', 'correction', 'all_clear', 'account')
    ),
    subject text not null,
    body text not null,
    thread_id text,
    created_at text not null
);"""
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
    link text,
    thread_id text
);
create table if not exists deliveries (
    alert_id text not null references alerts (id),
    account_id text not null references accounts (id),
    client text not null check (client in ('web', 'ios')),
    shown_at text not null,
    primary key (alert_id, account_id, client)
);
{MAILBOX}
create table if not exists magic_tokens (
    hash text primary key,
    account_id text not null references accounts (id),
    issued_at text not null,
    expires_at text not null,
    used_at text
);
create table if not exists invites (
    id integer primary key,
    parent_id text not null references accounts (id),
    student_email text not null,
    status text not null check (status in ('pending', 'accepted', 'declined')),
    created_at text not null,
    relationship text
);
create table if not exists ask_usage (
    account_id text not null references accounts (id),
    day text not null,
    count integer not null,
    primary key (account_id, day)
);
create table if not exists notes (
    id integer primary key,
    thread_id text not null,
    account_id text not null references accounts (id),
    tag text not null,
    text text,
    state text not null check (state in ('held', 'pending', 'visible', 'hidden')),
    created_at text not null,
    updated_at text not null,
    unique (thread_id, account_id)
);
create table if not exists note_reports (
    note_id integer not null references notes (id) on delete cascade,
    account_id text not null references accounts (id),
    primary key (note_id, account_id)
);
create table if not exists bans (
    account_id text primary key references accounts (id),
    until text not null
);
create table if not exists settings (
    key text primary key,
    value text not null
);
create table if not exists consents (
    account_id text not null references accounts (id),
    kind text not null,
    version text not null,
    granted_at text,
    withdrawn_at text,
    primary key (account_id, kind)
);
create table if not exists subscriptions (
    account_id text not null references accounts (id),
    kind text not null,
    state text not null check (state in ('pending_confirm', 'active', 'unsubscribed')),
    primary key (account_id, kind)
);
create table if not exists sub_tokens (
    hash text primary key,
    account_id text not null references accounts (id),
    kind text not null,
    purpose text not null check (purpose in ('confirm', 'unsubscribe')),
    created_at text not null
);
create table if not exists survey_answers (
    account_id text not null references accounts (id),
    prompt text not null,
    q1 integer,
    q2 integer,
    q3 integer,
    answered_at text not null,
    primary key (account_id, prompt)
);
create table if not exists device_keys (
    account_id text primary key references accounts (id),
    key_id text not null,
    secret text not null,
    created_at text not null,
    delivered integer not null default 0
);
create table if not exists sent_keys (
    key text primary key,
    sent_at text not null
);
create table if not exists outbox (
    key text primary key,
    account_id text not null references accounts (id),
    kind text not null,
    to_address text not null,
    subject text not null,
    body text not null,
    unsubscribe_url text,
    status text not null check (status in ('queued', 'sent', 'failed')),
    attempts integer not null default 0,
    last_error_kind text,
    created_at text not null,
    sent_at text
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
    email: str | None = None  # self-service accounts only; stored lower-case
    self_service: bool = False


@dataclass(frozen=True)
class Zone:
    name: str
    lat: float
    lon: float
    radius_m: int
    id: int | None = None


@dataclass(frozen=True)
class Activity:
    segment_id: str
    window: str
    level: str
    reason: str
    incidents: int
    serious: int


class Store:
    def __init__(self, target: Path | str) -> None:
        """A SQLite file path (default), or a migrated Postgres URL (demo-db migrate)."""
        self._lock: AbstractContextManager[Any]
        if is_postgres_url(str(target)):
            self.path: Path | None = None
            self._lock = nullcontext()
            self._check_schema(str(target))
            self._db = Database(str(target))
            return
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = Database(path)
        self._db.execute("pragma foreign_keys = on")
        # Deleted rows (notes, accounts, links) are overwritten, not left in free pages.
        self._db.execute("pragma secure_delete = on")
        self._db.executescript(SCHEMA.replace("{MAILBOX}", MAILBOX))
        self._add_thread_column()
        self._add_account_columns()
        self._widen_mailbox_kinds()
        self._add_invite_relationship()

    @staticmethod
    def _check_schema(url: str) -> None:
        """Refuse to start on an empty or older Postgres schema (the message never has the URL)."""
        import psycopg

        from demo_server import migrate

        with psycopg.connect(url) as conn:
            have = migrate.current_version(conn)
        want = migrate.newest_version()
        if have < want:
            raise RuntimeError(
                f"The database schema is version {have}, the server needs {want}."
                " Run `make db-migrate` first."
            )

    def _add_thread_column(self) -> None:
        """Databases from before threads: add the column; each old alert is its own thread."""
        columns = {row[1] for row in self._db.execute("pragma table_info(alerts)")}
        if "thread_id" not in columns:
            with self._db:
                self._db.execute("alter table alerts add column thread_id text")
                self._db.execute("update alerts set thread_id = id where thread_id is null")

    def _add_account_columns(self) -> None:
        """Databases from before sign-up: add email and self_service; old rows keep working."""
        columns = {row[1] for row in self._db.execute("pragma table_info(accounts)")}
        with self._db:
            if "email" not in columns:
                self._db.execute("alter table accounts add column email text")
            if "self_service" not in columns:
                self._db.execute(
                    "alter table accounts add column self_service integer not null default 0"
                )
            self._db.execute(
                "create unique index if not exists accounts_email on accounts (email)"
                " where email is not null"
            )
            if "auth_user_id" not in columns:  # v13: Supabase Auth user, once known
                self._db.execute("alter table accounts add column auth_user_id text")
            self._db.execute(
                "create unique index if not exists accounts_auth_user on accounts (auth_user_id)"
                " where auth_user_id is not null"
            )

    def _add_invite_relationship(self) -> None:
        """Invites from before relationships: add the column; old invites show the parent's name."""
        columns = {row[1] for row in self._db.execute("pragma table_info(invites)")}
        if "relationship" not in columns:
            with self._db:
                self._db.execute("alter table invites add column relationship text")

    def _widen_mailbox_kinds(self) -> None:
        """Mailboxes from before sign-up do not accept the 'account' kind: rebuild, keep rows."""
        row = self._db.execute("select sql from sqlite_master where name = 'mailbox'").fetchone()
        if row and "'account'" not in row[0]:
            with self._db:
                self._db.execute("alter table mailbox rename to mailbox_old")
                self._db.execute(MAILBOX)
                self._db.execute("insert into mailbox select * from mailbox_old")
                self._db.execute("drop table mailbox_old")

    @_locked
    def database(self) -> dict[str, Any]:
        """Which database holds family data, in words; never a host, file path or credential."""
        if self._db.dialect == "sqlite":
            return {"backend": "sqlite", "label": "SQLite on this laptop", "schema_version": None}
        row = self._db.execute("select coalesce(max(version), 0) from schema_migrations").fetchone()
        version = int(row[0])
        return {
            "backend": "postgres",
            "label": f"Postgres (schema v{version})",
            "schema_version": version,
        }

    @_locked
    def close(self) -> None:
        self._db.close()

    @_locked
    def add_account(self, account: Account) -> None:
        with self._db:
            self._db.execute(
                # Upsert on the id only: an email already used by another account must fail, not
                # silently replace that account (which "insert or replace" would do).
                "insert into accounts (id, role, display_name, is_test, email, self_service)"
                " values (?, ?, ?, ?, ?, ?) on conflict (id) do update set role = excluded.role,"
                " display_name = excluded.display_name, is_test = excluded.is_test,"
                " email = excluded.email, self_service = excluded.self_service",
                (
                    account.id,
                    account.role,
                    account.display_name,
                    int(account.is_test),
                    account.email.lower() if account.email else None,
                    int(account.self_service),
                ),
            )

    @_locked
    def link(self, parent_id: str, student_id: str, label: str) -> None:
        with self._db:
            self._db.execute(LINK, (parent_id, student_id, label))
        self.ensure_key(student_id, datetime.now(UTC))

    @_locked
    def consents(self, account_id: str) -> dict[str, dict[str, Any]]:
        rows = self._db.execute(
            "select kind, version, granted_at, withdrawn_at from consents where account_id = ?",
            (account_id,),
        ).fetchall()
        keys = ("version", "granted_at", "withdrawn_at")
        return {r[0]: dict(zip(keys, r[1:], strict=True)) for r in rows}

    @_locked
    def set_consent(
        self, account_id: str, kind: str, granted: bool, version: str, now: datetime
    ) -> None:
        """Yes records the grant (and clears any withdrawal); no withdraws an earlier yes, or
        records a decline when there was none."""
        at = now.isoformat()
        with self._db:
            current = self._db.execute(
                "select granted_at from consents where account_id = ? and kind = ?",
                (account_id, kind),
            ).fetchone()
            if granted:
                self._db.execute(CONSENT, (account_id, kind, version, at, None))
            elif current and current[0]:
                self._db.execute(
                    "update consents set withdrawn_at = ? where account_id = ? and kind = ?",
                    (at, account_id, kind),
                )
            else:
                self._db.execute(CONSENT, (account_id, kind, version, None, None))

    @_locked
    def set_subscription(self, account_id: str, kind: str, state: str) -> None:
        with self._db:
            self._db.execute(
                upsert_sql(
                    "subscriptions", ("account_id", "kind", "state"), ("account_id", "kind")
                ),
                (account_id, kind, state),
            )

    @_locked
    def subscription(self, account_id: str, kind: str) -> str | None:
        row = self._db.execute(
            "select state from subscriptions where account_id = ? and kind = ?", (account_id, kind)
        ).fetchone()
        return str(row[0]) if row else None

    @_locked
    def add_sub_token(
        self, token_hash: str, account_id: str, kind: str, purpose: str, now: datetime
    ) -> None:
        with self._db:
            self._db.execute(
                "insert into sub_tokens values (?, ?, ?, ?, ?)",
                (token_hash, account_id, kind, purpose, now.isoformat()),
            )

    @_locked
    def sub_token(self, token_hash: str, purpose: str) -> dict[str, str] | None:
        row = self._db.execute(
            "select account_id, kind from sub_tokens where hash = ? and purpose = ?",
            (token_hash, purpose),
        ).fetchone()
        return {"account_id": str(row[0]), "kind": str(row[1])} if row else None

    @_locked
    def survey_prompts(self, account_id: str) -> set[str]:
        rows = self._db.execute(
            "select prompt from survey_answers where account_id = ?", (account_id,)
        ).fetchall()
        return {str(r[0]) for r in rows}

    @_locked
    def add_survey_answer(
        self, account_id: str, prompt: str, answers: list[int] | None, now: datetime
    ) -> None:
        q1, q2, q3 = answers if answers else (None, None, None)
        with self._db:
            self._db.execute(
                "insert into survey_answers values (?, ?, ?, ?, ?, ?)",
                (account_id, prompt, q1, q2, q3, now.isoformat()),
            )

    @_locked
    def survey_rows(self) -> list[tuple[Any, ...]]:
        """(prompt, q1, q2, q3) for every answer; skipped prompts have no numbers."""
        return self._db.execute("select prompt, q1, q2, q3 from survey_answers").fetchall()

    @_locked
    def threads_delivered_to(self, account_id: str) -> list[str]:
        rows = self._db.execute(
            "select distinct a.thread_id from deliveries d join alerts a on a.id = d.alert_id"
            " where d.account_id = ?",
            (account_id,),
        ).fetchall()
        return [str(r[0]) for r in rows]

    @_locked
    def reach(self) -> dict[str, int]:
        """How many family accounts ever saw an alert on a device, out of all family accounts."""
        family = self._db.execute(
            "select count(*) from accounts where role in ('student', 'parent')"
        ).fetchone()[0]
        reached = self._db.execute(
            "select count(distinct d.account_id) from deliveries d"
            " join accounts a on a.id = d.account_id where a.role in ('student', 'parent')"
        ).fetchone()[0]
        return {"family_accounts": int(family), "reached": int(reached)}

    @_locked
    def ensure_key(self, student_id: str, now: datetime) -> None:
        """A key for a newly linked student. A second parent linking keeps the phone's key; a
        relink after the last unlink gets a fresh one (unlink drops it)."""
        if self.device_key(student_id) is None:
            self.provision_key(student_id, now)

    @_locked
    def thread_info(self, thread_id: str) -> dict[str, Any] | None:
        """An alert thread for notes: its words, whether test accounts only, when it opened and
        when IU's all-clear ("Normal") closed it (None while open)."""
        rows = self._db.execute(
            "select stored_text, test_only, status, received_at from alerts where thread_id = ?"
            " order by received_at",
            (thread_id,),
        ).fetchall()
        if not rows:
            return None
        closed = next((r[3] for r in rows if str(r[2]).strip().lower() == "normal"), None)
        return {
            "text": " ".join(str(r[0]) for r in rows),
            "test_only": bool(rows[0][1]),
            "opened_at": datetime.fromisoformat(rows[0][3]),
            "last_at": datetime.fromisoformat(rows[-1][3]),
            "closed_at": datetime.fromisoformat(closed) if closed else None,
        }

    # Community notes (v9): no location anywhere; one note per person per incident thread.
    NOTE_COLUMNS = ("id", "thread_id", "account_id", "tag", "text", "state", "created_at")

    @_locked
    def put_note(
        self,
        thread_id: str,
        account_id: str,
        tag: str,
        text: str | None,
        state: str,
        now: datetime,
    ) -> int:
        """Create, or edit the person's existing note on this thread. Returns its id."""
        at = now.isoformat()
        with self._db:
            self._db.execute(
                "insert into notes"
                " (thread_id, account_id, tag, text, state, created_at, updated_at)"
                " values (?, ?, ?, ?, ?, ?, ?) on conflict (thread_id, account_id) do update set"
                " tag = excluded.tag, text = excluded.text, state = excluded.state,"
                " updated_at = excluded.updated_at",
                (thread_id, account_id, tag, text, state, at, at),
            )
            row = self._db.execute(
                "select id from notes where thread_id = ? and account_id = ?",
                (thread_id, account_id),
            ).fetchone()
        return int(row[0])

    @_locked
    def note(self, note_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            f"select {', '.join(self.NOTE_COLUMNS)} from notes where id = ?",  # noqa: S608 (fixed names)
            (note_id,),
        ).fetchone()
        return dict(zip(self.NOTE_COLUMNS, row, strict=True)) if row else None

    @_locked
    def notes_of(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            f"select {', '.join(self.NOTE_COLUMNS)} from notes where thread_id = ? order by id",  # noqa: S608
            (thread_id,),
        ).fetchall()
        return [dict(zip(self.NOTE_COLUMNS, r, strict=True)) for r in rows]

    @_locked
    def notes_in(self, state: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            f"select {', '.join(self.NOTE_COLUMNS)} from notes where state = ? order by id",  # noqa: S608
            (state,),
        ).fetchall()
        return [dict(zip(self.NOTE_COLUMNS, r, strict=True)) for r in rows]

    @_locked
    def set_note_state(self, note_id: int, state: str) -> None:
        with self._db:
            self._db.execute("update notes set state = ? where id = ?", (state, note_id))

    @_locked
    def delete_note(self, note_id: int) -> bool:
        with self._db:
            return bool(self._db.execute("delete from notes where id = ?", (note_id,)).rowcount)

    @_locked
    def delete_notes(self, thread_id: str | None = None, account_id: str | None = None) -> int:
        """All notes of a thread (expiry) or of a person (ban, delete)."""
        with self._db:
            if thread_id is not None:
                cursor = self._db.execute("delete from notes where thread_id = ?", (thread_id,))
            else:
                cursor = self._db.execute("delete from notes where account_id = ?", (account_id,))
        return int(cursor.rowcount)

    @_locked
    def expire_notes(self, now: datetime, hours: int) -> int:
        """Delete every note whose incident closed more than `hours` ago: closed by IU's
        all-clear, or gone quiet (no update for THREAD_GAP). No history is kept."""
        threads = [r[0] for r in self._db.execute("select distinct thread_id from notes")]
        deleted = 0
        for thread_id in threads:
            info = self.thread_info(thread_id)
            closed = info and (info["closed_at"] or info["last_at"] + THREAD_GAP)
            if info is None or (closed and now - closed > timedelta(hours=hours)):
                deleted += self.delete_notes(thread_id=thread_id)
        return deleted

    @_locked
    def add_report(self, note_id: int, account_id: str) -> bool:
        """False when this person already reported this note."""
        with self._db:
            return bool(
                self._db.execute(
                    insert_ignore_sql("note_reports", ("note_id", "account_id")),
                    (note_id, account_id),
                ).rowcount
            )

    @_locked
    def report_count(self, note_id: int) -> int:
        row = self._db.execute(
            "select count(*) from note_reports where note_id = ?", (note_id,)
        ).fetchone()
        return int(row[0])

    @_locked
    def ban(self, account_id: str, until: datetime) -> None:
        with self._db:
            self._db.execute(
                upsert_sql("bans", ("account_id", "until"), ("account_id",)),
                (account_id, until.isoformat()),
            )

    @_locked
    def banned(self, account_id: str, now: datetime) -> bool:
        row = self._db.execute(
            "select until from bans where account_id = ?", (account_id,)
        ).fetchone()
        return bool(row) and datetime.fromisoformat(row[0]) > now

    @_locked
    def setting(self, key: str, default: str) -> str:
        row = self._db.execute("select value from settings where key = ?", (key,)).fetchone()
        return str(row[0]) if row else default

    @_locked
    def set_setting(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(upsert_sql("settings", ("key", "value"), ("key",)), (key, value))

    @_locked
    def provision_key(self, student_id: str, now: datetime) -> tuple[str, str]:
        """A fresh demo signing key for the student's device (a relink rotates it)."""
        key_id, secret = signing.new_key()
        with self._db:
            self._db.execute(
                upsert_sql(
                    "device_keys",
                    ("account_id", "key_id", "secret", "created_at", "delivered"),
                    ("account_id",),
                ),
                (student_id, key_id, secret, now.isoformat(), 0),
            )
        return key_id, secret

    @_locked
    def device_key(self, student_id: str) -> tuple[str, str] | None:
        row = self._db.execute(
            "select key_id, secret from device_keys where account_id = ?", (student_id,)
        ).fetchone()
        return (str(row[0]), str(row[1])) if row else None

    @_locked
    def take_undelivered_key(self, student_id: str) -> tuple[str, str] | None:
        """The key, once: later calls return None until the next rotation."""
        with self._db:
            row = self._db.execute(
                "select key_id, secret from device_keys where account_id = ? and delivered = 0",
                (student_id,),
            ).fetchone()
            if row:
                self._db.execute(
                    "update device_keys set delivered = 1 where account_id = ?", (student_id,)
                )
        return (str(row[0]), str(row[1])) if row else None

    @_locked
    def add_zone(self, account_id: str, zone: Zone) -> None:
        with self._db:
            self._db.execute(
                "insert into zones (account_id, name, lat, lon, radius_m) values (?, ?, ?, ?, ?)",
                (account_id, zone.name, zone.lat, zone.lon, zone.radius_m),
            )

    @_locked
    def accounts(self) -> list[Account]:
        rows = self._db.execute(
            "select id, role, display_name, is_test, email, self_service from accounts"
            " order by role, display_name"
        ).fetchall()
        return [Account(r[0], r[1], r[2], bool(r[3]), r[4], bool(r[5])) for r in rows]

    @_locked
    def auth_user(self, account_id: str) -> str | None:
        row = self._db.execute(
            "select auth_user_id from accounts where id = ?", (account_id,)
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    @_locked
    def set_auth_user(self, account_id: str, user_id: str) -> None:
        with self._db:
            self._db.execute(
                "update accounts set auth_user_id = ? where id = ?", (user_id, account_id)
            )

    # Real email (EMAIL_MODE=smtp): an outbox that survives a restart; bodies cleared once sent.
    OUTBOX = ("key", "account_id", "kind", "to_address", "subject", "body", "unsubscribe_url")

    @_locked
    def outbox_add(self, row: tuple[Any, ...], now: datetime) -> bool:
        """Queue one email (row in OUTBOX order); False when its key is already queued or sent."""
        columns = (*self.OUTBOX, "status", "created_at")
        return bool(
            self._db.execute(
                insert_ignore_sql("outbox", columns), (*row, "queued", now.isoformat())
            ).rowcount
        )

    @_locked
    def outbox_due(self, max_attempts: int) -> list[dict[str, Any]]:
        rows = self._db.execute(
            f"select {', '.join(self.OUTBOX)}, attempts from outbox"  # noqa: S608 (fixed names)
            " where status = 'queued' and attempts < ? order by created_at, key",
            (max_attempts,),
        ).fetchall()
        return [dict(zip((*self.OUTBOX, "attempts"), r, strict=True)) for r in rows]

    @_locked
    def outbox_sent(self, key: str, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "update outbox set status = 'sent', sent_at = ?, body = '', attempts = attempts + 1"
                " where key = ?",
                (now.isoformat(), key),
            )

    @_locked
    def outbox_failed(self, key: str, error_kind: str, max_attempts: int) -> None:
        with self._db:
            self._db.execute(
                "update outbox set attempts = attempts + 1, last_error_kind = ?,"
                " status = case when attempts + 1 >= ? then 'failed' else 'queued' end"
                " where key = ?",
                (error_kind, max_attempts, key),
            )

    @_locked
    def outbox_to_since(self, address: str, since: datetime) -> int:
        row = self._db.execute(
            "select count(*) from outbox where to_address = ? and created_at >= ?",
            (address, since.isoformat()),
        ).fetchone()
        return int(row[0])

    @_locked
    def email_confirmed(self, account_id: str) -> bool:
        """The address proved it is theirs: a Supabase sign-in, a used sign-in link, or a confirmed
        subscription."""
        row = self._db.execute(
            "select (select count(*) from accounts where id = ? and auth_user_id is not null)"
            " + (select count(*) from magic_tokens where account_id = ? and used_at is not null)"
            " + (select count(*) from subscriptions where account_id = ? and state = 'active')",
            (account_id, account_id, account_id),
        ).fetchone()
        return int(row[0]) > 0

    @_locked
    def outbox_counts(self) -> dict[str, int]:
        rows = self._db.execute("select status, count(*) from outbox group by status").fetchall()
        return {str(status): int(n) for status, n in rows}

    @_locked
    def account_by_email(self, email: str) -> Account | None:
        return next((a for a in self.accounts() if a.email == email.strip().lower()), None)

    @_locked
    def account(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts() if a.id == account_id), None)

    @_locked
    def students_of(self, parent_id: str) -> list[str]:
        rows = self._db.execute(
            "select student_id from links where parent_id = ? order by student_id", (parent_id,)
        )
        return [r[0] for r in rows]

    @_locked
    def parents_of(self, student_id: str) -> dict[str, str]:
        """Linked parent id -> the label the student knows them by ("Mom")."""
        rows = self._db.execute(
            "select parent_id, parent_label from links where student_id = ?", (student_id,)
        )
        return dict(rows.fetchall())

    @_locked
    def zones(self, account_id: str) -> list[Zone]:
        rows = self._db.execute(
            "select name, lat, lon, radius_m, id from zones where account_id = ? order by id",
            (account_id,),
        )
        return [Zone(*r) for r in rows]

    @_locked
    def save_zone(self, account_id: str, zone: Zone) -> int | None:
        """Add (zone.id None) or update one of the account's own zones; None when the id is not
        theirs."""
        with self._db:
            if zone.id is None:
                row = self._db.execute(
                    "insert into zones (account_id, name, lat, lon, radius_m)"
                    " values (?, ?, ?, ?, ?) returning id",
                    (account_id, zone.name, zone.lat, zone.lon, zone.radius_m),
                ).fetchone()
                return int(row[0])
            changed = self._db.execute(
                "update zones set name = ?, lat = ?, lon = ?, radius_m = ?"
                " where id = ? and account_id = ?",
                (zone.name, zone.lat, zone.lon, zone.radius_m, zone.id, account_id),
            ).rowcount
        return zone.id if changed else None

    @_locked
    def delete_zone(self, account_id: str, zone_id: int) -> bool:
        with self._db:
            return bool(
                self._db.execute(
                    "delete from zones where id = ? and account_id = ?", (zone_id, account_id)
                ).rowcount
            )

    def add_alert(
        self, alert_id: str, alert: OfficialAlert, received_at: datetime, thread_id: str
    ) -> None:
        with self._db:
            self._db.execute(
                "insert into alerts (id, source, kind, status, verification, test_only,"
                " official_at, received_at, stored_text, link, thread_id)"
                " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    thread_id,
                ),
            )

    @_locked
    def alerts(self, include_test: bool, limit: int = 50) -> list[dict[str, object]]:
        rows = self._db.execute(
            "select id, source, kind, status, verification, official_at, received_at,"
            " stored_text, link, thread_id from alerts where (test_only = 0 or ? = 1)"
            " order by received_at desc limit ?",
            (int(include_test), limit),
        )
        keys = ["id", "source", "kind", "status", "verification", "official_at"]
        keys += ["received_at", "text", "link", "thread_id"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    @_locked
    def metric_rows(
        self,
    ) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        """Raw rows for metrics.alert_metrics: deliveries with their alert's card, words and
        received time; IU alerts (id, received); follow-up mail (account, kind, card, words, at)."""
        deliveries = self._db.execute(
            "select d.account_id, d.client, d.shown_at, a.id, a.thread_id, a.stored_text,"
            " a.received_at from deliveries d join alerts a on a.id = d.alert_id"
        ).fetchall()
        official = self._db.execute("select id, received_at from alerts").fetchall()
        mail = self._db.execute(
            "select account_id, kind, thread_id, body, created_at from mailbox"
            " where kind in ('alert', 'correction', 'all_clear') and thread_id is not null"
        ).fetchall()
        return deliveries, official, mail

    @_locked
    def delivered(self, alert_id: str, account_id: str, client: str, shown_at: datetime) -> None:
        with self._db:
            self._db.execute(
                insert_ignore_sql("deliveries", ("alert_id", "account_id", "client", "shown_at")),
                (alert_id, account_id, client, shown_at.isoformat()),
            )

    @_locked
    def latency(self, limit: int = 20) -> list[dict[str, object]]:
        """Per alert: official time, server received, first shown on web and on iPhone."""
        rows = self._db.execute(
            """
            select a.id, a.thread_id, a.kind, a.verification, a.status, a.official_at,
                   a.received_at, min(case when d.client = 'web' then d.shown_at end),
                   min(case when d.client = 'ios' then d.shown_at end)
            from alerts a left join deliveries d on d.alert_id = a.id
            group by a.id order by a.received_at desc limit ?
            """,
            (limit,),
        )
        keys = ["id", "thread_id", "kind", "verification", "status", "official_at"]
        keys += ["received_at", "web_at", "ios_at"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    @_locked
    def deliver_mail(
        self,
        key: str,
        account_id: str,
        kind: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
    ) -> bool:
        """One message per key: a repeated key (the same briefing, digest or follow-up) is a
        no-op and returns False."""
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._db:
            fresh = self._db.execute(
                insert_ignore_sql("sent_keys", ("key", "sent_at")), (key, now)
            ).rowcount
            if fresh:
                self._db.execute(
                    "insert into mailbox (account_id, kind, subject, body, thread_id, created_at)"
                    " values (?, ?, ?, ?, ?, ?)",
                    (account_id, kind, subject, body, thread_id, now),
                )
        return bool(fresh)

    @_locked
    def add_magic(
        self, digest: str, account_id: str, issued_at: datetime, expires_at: datetime
    ) -> None:
        with self._db:
            self._db.execute(
                "insert into magic_tokens values (?, ?, ?, ?, null)",
                (digest, account_id, issued_at.isoformat(), expires_at.isoformat()),
            )

    @_locked
    def magic_issued_since(self, account_id: str, since: datetime) -> int:
        row = self._db.execute(
            "select count(*) from magic_tokens where account_id = ? and issued_at >= ?",
            (account_id, since.isoformat()),
        ).fetchone()
        return int(row[0]) if row else 0

    @_locked
    def magic(self, digest: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "select hash, account_id, expires_at, used_at from magic_tokens where hash = ?",
            (digest,),
        ).fetchone()
        if row is None:
            return None
        return {
            "hash": row[0],
            "account_id": row[1],
            "expires_at": datetime.fromisoformat(row[2]),
            "used_at": row[3],
        }

    @_locked
    def use_magic(self, digest: str, now: datetime) -> bool:
        """Marks the token used; False if another request used it first."""
        with self._db:
            return bool(
                self._db.execute(
                    "update magic_tokens set used_at = ? where hash = ? and used_at is null",
                    (now.isoformat(), digest),
                ).rowcount
            )

    @_locked
    def magic_rows(self) -> list[tuple[Any, ...]]:
        return self._db.execute("select * from magic_tokens").fetchall()

    @_locked
    def add_invite(
        self, parent_id: str, student_email: str, now: datetime, relationship: str | None = None
    ) -> int | None:
        """A pending invite, or None when one is already pending (expired ones do not count)."""
        email, since = student_email.strip().lower(), (now - INVITE_LIFETIME).isoformat()
        with self._db:
            if self._db.execute(
                "select 1 from invites where parent_id = ? and student_email = ?"
                " and status = 'pending' and created_at >= ?",
                (parent_id, email, since),
            ).fetchone():
                return None
            row = self._db.execute(
                "insert into invites (parent_id, student_email, status, created_at, relationship)"
                " values (?, ?, 'pending', ?, ?) returning id",
                (parent_id, email, now.isoformat(), relationship),
            ).fetchone()
        return int(row[0])

    @_locked
    def invites(self, account: "Account", now: datetime) -> list[dict[str, Any]]:
        """Students see invites to their email; parents see the ones they sent. Expired pending
        invites (older than 7 days) are not shown."""
        since = (now - INVITE_LIFETIME).isoformat()
        rows = self._db.execute(
            "select i.id, a.display_name, i.student_email, i.status, i.created_at,"
            " coalesce(i.relationship, a.display_name)"
            " from invites i join accounts a on a.id = i.parent_id"
            " where ((? = 'student' and i.student_email = ?) or (? = 'parent' and i.parent_id = ?))"
            " and (i.status != 'pending' or i.created_at >= ?) order by i.id desc",
            (account.role, account.email, account.role, account.id, since),
        )
        names = ("id", "from", "student_email", "status", "created_at", "relationship")
        return [dict(zip(names, r, strict=True)) for r in rows]

    @_locked
    def answer_invite(
        self, invite_id: int, student: "Account", accept: bool, now: datetime
    ) -> str | None:
        """The student's answer to a pending, unexpired invite addressed to their email. Returns the
        parent id, or None when there is no such invite for this student."""
        since = (now - INVITE_LIFETIME).isoformat()
        with self._db:
            row = self._db.execute(
                "select parent_id, relationship from invites where id = ? and student_email = ?"
                " and status = 'pending' and created_at >= ?",
                (invite_id, student.email, since),
            ).fetchone()
            if row is None or student.role != "student":
                return None
            status = "accepted" if accept else "declined"
            self._db.execute("update invites set status = ? where id = ?", (status, invite_id))
            if accept:
                parent = self._db.execute(
                    "select display_name from accounts where id = ?", (row[0],)
                ).fetchone()
                label = row[1] or parent[0]  # what the student sees: "Mom", "Guardian", own words
                self._db.execute(LINK, (row[0], student.id, label))
        if accept:
            self.ensure_key(student.id, now)
        return str(row[0])

    @_locked
    def unlink(self, parent_id: str, student_id: str) -> bool:
        with self._db:
            removed = bool(
                self._db.execute(
                    "delete from links where parent_id = ? and student_id = ?",
                    (parent_id, student_id),
                ).rowcount
            )
            left = self._db.execute(
                "select count(*) from links where student_id = ?", (student_id,)
            ).fetchone()[0]
            if not left:  # nobody can ask any more: the next link gets a fresh key
                self._db.execute("delete from device_keys where account_id = ?", (student_id,))
        return removed

    @_locked
    def delete_account(self, account: "Account") -> None:
        """Everything the account owns, in one transaction: links on either side, invites it sent
        or that were sent to its email, zones, mailbox, sign-in links, deliveries, the keys of
        messages sent to it, and the account itself."""
        with self._db:
            self._db.execute(
                "delete from links where parent_id = ? or student_id = ?", (account.id, account.id)
            )
            self._db.execute(
                "delete from invites where parent_id = ? or student_email = ?",
                (account.id, account.email),
            )
            for table in (
                "zones",
                "mailbox",
                "magic_tokens",
                "deliveries",
                "ask_usage",
                "device_keys",
                "consents",
                "subscriptions",
                "sub_tokens",
                "survey_answers",
                "note_reports",
                "notes",
                "bans",
                "outbox",
            ):
                self._db.execute(f"delete from {table} where account_id = ?", (account.id,))  # noqa: S608 (fixed names)
            pattern = "%" + re.sub(r"([\\%_])", r"\\\1", account.id) + "%"
            self._db.execute("delete from sent_keys where key like ? escape '\\'", (pattern,))
            self._db.execute("delete from accounts where id = ?", (account.id,))

    @_locked
    def take_ask(self, account_id: str, day: str, limit: int) -> bool:
        """Counts one question; False (and nothing counted) once the day's limit is reached."""
        with self._db:
            row = self._db.execute(
                "select count from ask_usage where account_id = ? and day = ?", (account_id, day)
            ).fetchone()
            if row and row[0] >= limit:
                return False
            self._db.execute(
                "insert into ask_usage values (?, ?, 1) on conflict (account_id, day)"
                " do update set count = ask_usage.count + 1",
                (account_id, day),
            )
        return True

    @_locked
    def sent(self, key: str) -> bool:
        return (
            self._db.execute("select 1 from sent_keys where key = ?", (key,)).fetchone() is not None
        )

    @_locked
    def mailbox(self, account_id: str, limit: int = 50) -> list[dict[str, object]]:
        rows = self._db.execute(
            "select id, kind, subject, body, thread_id, created_at from mailbox"
            " where account_id = ? order by id desc limit ?",
            (account_id, limit),
        )
        names = ("id", "kind", "subject", "body", "thread_id", "created_at")
        return [dict(zip(names, row, strict=True)) for row in rows]

    @_locked
    def replace_activity(self, rows: list[Activity]) -> None:
        with self._db:
            self._db.execute("delete from activity")
            for r in rows:
                self._db.execute(
                    "insert into activity values (?, ?, ?, ?, ?, ?)",
                    (r.segment_id, r.window, r.level, r.reason, r.incidents, r.serious),
                )

    @_locked
    def activity(self) -> list[Activity]:
        rows = self._db.execute("select * from activity order by segment_id, time_window")
        return [Activity(*r) for r in rows]
