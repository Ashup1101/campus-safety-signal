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


def check(url: str) -> tuple[bool, list[str]]:
    """Connected, schema version, RLS on every table, no policies: names and counts only."""
    try:
        conn = psycopg.connect(url, connect_timeout=10)
    except psycopg.Error as exc:
        return False, [f"connected: no ({type(exc).__name__})"]
    with conn:
        have, want = current_version(conn), newest_version()
        tables = conn.execute(
            "select c.relname, c.relrowsecurity from pg_class c"
            " join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'public' and c.relkind = 'r' order by c.relname"
        ).fetchall()
        row = conn.execute(
            "select count(*) from pg_policies where schemaname = 'public'"
        ).fetchone()
        policies = int(row[0]) if row else 0
    open_tables = [str(name) for name, secured in tables if not secured]
    lines = [
        "connected: yes",
        f"schema version: {have} (newest {want})",
        f"tables: {len(tables)}, row-level security on: {len(tables) - len(open_tables)}",
        f"public policies: {policies}",
    ]
    if open_tables:
        lines.append("tables without row-level security: " + ", ".join(open_tables))
    ok = have == want and not open_tables and policies == 0 and len(tables) > 0
    return ok, lines


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(
        prog="demo-db", description="Postgres schema for the demo server (DEMO_DATABASE_URL)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("migrate", help="apply pending migrations")
    run.add_argument("--dry-run", action="store_true", help="print the pending SQL, apply nothing")
    sub.add_parser("check", help="connected, schema version, row-level security (no data shown)")
    args = parser.parse_args(argv)
    url = os.environ.get("DEMO_DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        print("DEMO_DATABASE_URL is not set to a Postgres connection string.")
        return 1
    try:
        if args.command == "check":
            ok, lines = check(url)
            print("\n".join(lines))
            print("check: ok" if ok else "check: FAILED")
            return 0 if ok else 1
        if args.dry_run:
            with psycopg.connect(url, connect_timeout=10) as conn:
                todo = pending(conn)
            for version, path in todo:
                print(f"-- {version:04d}: {path.name}\n{path.read_text()}")
            print(f"-- {len(todo)} pending migration(s); nothing applied")
            return 0
        applied = migrate(url)
    except psycopg.Error as exc:  # never the URL: only the kind of error
        print(f"database error: {type(exc).__name__}")
        return 1
    print(f"applied: {applied or 'nothing (already up to date)'}; version {newest_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
