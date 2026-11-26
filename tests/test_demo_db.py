from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from demo_server import migrate
from demo_server.db import (
    Database,
    IntegrityError,
    insert_ignore_sql,
    is_postgres_url,
    to_postgres,
    upsert_sql,
)


def test_embedded_postgres_answers(pg_url: str) -> None:
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("select 1").fetchone() == (1,)


@pytest.fixture(params=["sqlite", "postgres"])
def database(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Database]:
    target = (
        tmp_path / "t.sqlite3" if request.param == "sqlite" else request.getfixturevalue("pg_url")
    )
    db = Database(target)
    db.executescript("create table kv (k text primary key, v text not null, n integer)")
    yield db
    db.close()


def test_placeholders_convert_and_keep_literal_percent() -> None:
    assert to_postgres("select ? where x like '%a'") == "select %s where x like '%%a'"


def test_upsert_replaces_and_insert_ignore_keeps(database: Database) -> None:
    put = upsert_sql("kv", ["k", "v", "n"], ["k"])
    database.execute(put, ("a", "one", 1))
    database.execute(put, ("a", "two", 2))
    keep = insert_ignore_sql("kv", ["k", "v", "n"])
    assert database.execute(keep, ("a", "three", 3)).rowcount == 0
    assert database.execute(keep, ("b", "bee", None)).rowcount == 1
    rows = database.execute("select k, v, n from kv where k like ? order by k", ("%",)).fetchall()
    assert rows == [("a", "two", 2), ("b", "bee", None)]


def test_transaction_rolls_back_on_error(database: Database) -> None:
    with pytest.raises(RuntimeError), database:
        database.execute("insert into kv values (?, ?, ?)", ("x", "y", 0))
        with database:  # nested block: the outer one decides
            database.execute("insert into kv values (?, ?, ?)", ("z", "y", 0))
        raise RuntimeError
    assert database.execute("select count(*) from kv").fetchone() == (0,)
    with database:
        database.execute("insert into kv values (?, ?, ?)", ("x", "y", 0))
    assert database.execute("select count(*) from kv").fetchone() == (1,)


def test_duplicate_key_raises_the_same_way(database: Database) -> None:
    database.execute("insert into kv values (?, ?, ?)", ("x", "y", 0))
    with pytest.raises(IntegrityError):
        database.execute("insert into kv values (?, ?, ?)", ("x", "y", 0))


def test_upsert_rejects_odd_names() -> None:
    with pytest.raises(ValueError, match="bad column"):
        upsert_sql("kv; drop table kv", ["k"], ["k"])


def test_postgres_url_detection() -> None:
    assert is_postgres_url("postgresql://u@h/db") and is_postgres_url("postgres://u@h/db")
    assert not is_postgres_url(None) and not is_postgres_url("data/demo/demo.sqlite3")


def _tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "select tablename from pg_tables where schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def test_migrations_create_the_family_schema_once(pg_url: str) -> None:
    assert migrate.migrate(pg_url) == list(range(1, migrate.newest_version() + 1))
    tables = _tables(pg_url)
    assert len(tables - {"schema_migrations"}) == 20 and "schema_migrations" in tables
    assert migrate.migrate(pg_url) == []  # second run is a no-op
    with psycopg.connect(pg_url) as conn:
        assert migrate.current_version(conn) == migrate.newest_version()


def test_migration_numbers_must_not_skip(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("select 1;")
    (tmp_path / "0003_c.sql").write_text("select 1;")
    with pytest.raises(ValueError, match="without gaps"):
        migrate.migration_files(tmp_path)
