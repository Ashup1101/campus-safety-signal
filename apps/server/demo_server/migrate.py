"""Numbered Postgres migrations for the demo store (SQLite keeps its create-if-missing path).

Files are apps/server/migrations/postgres/NNNN_name.sql, applied in order, each in its own
transaction, and recorded in schema_migrations. Applying again changes nothing.
"""

from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "postgres"
LOCK_ID = 7_312_012  # advisory lock: two servers starting at once must not both migrate
LEDGER = (
    "create table if not exists schema_migrations"
    " (version integer primary key, applied_at text not null)"
)


def migration_files(folder: Path = MIGRATIONS) -> list[tuple[int, Path]]:
    files = sorted(
        (int(p.name.split("_", 1)[0]), p) for p in folder.glob("[0-9][0-9][0-9][0-9]_*.sql")
    )
    versions = [v for v, _ in files]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError("migration numbers must run 1, 2, 3 ... without gaps")
    return files


def newest_version(folder: Path = MIGRATIONS) -> int:
    files = migration_files(folder)
    return files[-1][0] if files else 0


def current_version(conn: psycopg.Connection) -> int:
    exists = conn.execute("select to_regclass('schema_migrations') is not null").fetchone()
    if not exists or not exists[0]:
        return 0
    row = conn.execute("select coalesce(max(version), 0) from schema_migrations").fetchone()
    return int(row[0]) if row else 0


def pending(conn: psycopg.Connection, folder: Path = MIGRATIONS) -> list[tuple[int, Path]]:
    done = current_version(conn)
    return [(v, p) for v, p in migration_files(folder) if v > done]


def migrate(url: str, folder: Path = MIGRATIONS) -> list[int]:
    """Apply every pending file; returns the versions applied (empty when up to date)."""
    applied: list[int] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(LEDGER)
            for version, path in pending(conn, folder):
                with conn.transaction():
                    conn.execute(path.read_text())  # checked-in SQL
                    conn.execute(
                        "insert into schema_migrations values (%s, to_char(now() at time zone"
                        " 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"'))",
                        (version,),
                    )
                applied.append(version)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied
