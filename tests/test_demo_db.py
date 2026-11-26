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
from demo_server.seed import Settings
from demo_server.store import Store


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


def test_every_table_has_rls_on_and_no_policies(pg_url: str) -> None:
    migrate.migrate(pg_url)
    with psycopg.connect(pg_url) as conn:
        off = conn.execute(
            "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity"
        ).fetchall()
        policies = conn.execute(
            "select count(*) from pg_policies where schemaname = 'public'"
        ).fetchone()
    assert off == [] and policies == (0,)


def test_a_role_without_bypass_sees_no_rows(pg_url: str) -> None:
    migrate.migrate(pg_url)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("insert into settings values ('k', 'v')")
        conn.execute("create role anon_test nologin")
        conn.execute("grant select on settings to anon_test")
        conn.execute("set role anon_test")
        assert conn.execute("select count(*) from settings").fetchone() == (0,)
        conn.execute("reset role")


def test_store_refuses_an_unmigrated_database_without_showing_the_url(pg_url: str) -> None:
    with pytest.raises(RuntimeError, match="make db-migrate") as found:
        Store(pg_url)
    assert "postgresql" not in str(found.value) and "host=" not in str(found.value)
    migrate.migrate(pg_url)
    Store(pg_url).close()


def test_settings_pick_the_backend_and_hide_the_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert Settings(data_dir=tmp_path).db == tmp_path / "demo.sqlite3"
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgresql://svc:secret@db.example.test/postgres")
    settings = Settings(data_dir=tmp_path)
    assert settings.db == "postgresql://svc:secret@db.example.test/postgres"
    assert "secret" not in repr(settings)


def test_cli_migrate_dry_run_then_migrate_then_check(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEMO_DATABASE_URL", pg_url)
    assert migrate.main(["check"]) == 1  # empty database: version 0
    assert migrate.main(["migrate", "--dry-run"]) == 0
    assert "create table accounts" in capsys.readouterr().out
    assert _tables(pg_url) == set()
    assert migrate.main(["migrate"]) == 0
    assert migrate.main(["migrate"]) == 0  # idempotent
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("insert into settings values ('k', 'a-private-value')")
    assert migrate.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "check: ok" in out and "public policies: 0" in out
    assert "a-private-value" not in out and "host=" not in out and "postgresql" not in out


def test_cli_check_fails_on_an_open_table_or_a_policy(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEMO_DATABASE_URL", pg_url)
    migrate.migrate(pg_url)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("alter table notes disable row level security")
        conn.execute("create policy everyone on bans for select using (true)")
    assert migrate.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "without row-level security: notes" in out and "public policies: 1" in out


def test_cli_needs_a_postgres_url_and_hides_connection_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert migrate.main(["check"]) == 1
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgresql://svc:secret@127.0.0.1:1/postgres")
    assert migrate.main(["check"]) == 1
    assert migrate.main(["migrate"]) == 1
    out = capsys.readouterr().out
    assert "secret" not in out and "connected: no" in out


def test_cli_reads_the_url_from_dotenv(
    pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"OTHER=1\nDEMO_DATABASE_URL='{pg_url}'\n")
    monkeypatch.setenv("CAMPUS_SAFETY_DOTENV", str(dotenv))
    monkeypatch.setenv("DEMO_DATABASE_URL", "")  # empty: .env fills it; undone after the test
    assert migrate.main(["migrate"]) == 0 and migrate.main(["check"]) == 0


def test_a_rejected_duplicate_rolls_back_its_block_and_the_database_keeps_working(
    database: Database,
) -> None:
    database.execute("insert into kv values (?, ?, ?)", ("x", "y", 0))
    with pytest.raises(IntegrityError), database:
        database.execute("insert into kv values (?, ?, ?)", ("new", "y", 0))
        database.execute("insert into kv values (?, ?, ?)", ("x", "y", 0))
    assert database.execute("select k from kv order by k").fetchall() == [("x",)]
    with database:
        database.execute("insert into kv values (?, ?, ?)", ("z", "y", 0))
    assert database.execute("select count(*) from kv").fetchone() == (2,)


def test_postgres_never_prepares_statements_for_the_transaction_pooler(pg_url: str) -> None:
    db = Database(pg_url)
    for _ in range(12):  # psycopg would prepare after 5 runs by default
        db.execute("select count(*) from pg_class where relname = ?", ("x",))
    with db:
        assert db.execute("select count(*) from pg_prepared_statements").fetchone() == (0,)
    db.close()
