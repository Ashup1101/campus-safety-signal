import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from demo_server.db import is_postgres_url
from demo_server.seed import Settings


def store_at(tmp_path: Path) -> Path | str:
    """The database a test's app uses: Postgres in `--demo-db postgres` runs, else a SQLite file."""
    return Settings(data_dir=tmp_path).db


def _query(target: Path | str, sql: str) -> list[tuple[Any, ...]]:
    if is_postgres_url(str(target)):
        import psycopg

        with psycopg.connect(str(target)) as conn:
            return [tuple(r) for r in conn.execute(sql).fetchall()]
    with closing(sqlite3.connect(target)) as conn:
        return conn.execute(sql).fetchall()


def tables(target: Path | str) -> list[str]:
    """The family tables (not the migrations ledger) on either backend."""
    sql = (
        "select tablename from pg_tables where schemaname = 'public'"
        " and tablename != 'schema_migrations'"
        if is_postgres_url(str(target))
        else "select name from sqlite_master where type = 'table'"
    )
    return [str(r[0]) for r in _query(target, sql)]


def columns(target: Path | str, table: str) -> set[str]:
    if is_postgres_url(str(target)):
        sql = f"select column_name from information_schema.columns where table_name = '{table}'"  # noqa: S608
        return {str(r[0]) for r in _query(target, sql)}
    return {str(r[1]) for r in _query(target, f"pragma table_info({table})")}


def rows(target: Path | str, table: str) -> list[tuple[Any, ...]]:
    return _query(target, f"select * from {table}")  # noqa: S608 (names from the catalog)
