import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from campus_safety.env import DOTENV_VAR


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """CLIs load model keys from .env; tests must never see the owner's real keys."""
    monkeypatch.setenv(DOTENV_VAR, str(tmp_path_factory.getbasetemp() / "no.env"))
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DEMO_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def _pg_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    """One embedded Postgres (no Docker) per run; skips if the package or binaries are missing."""
    pgserver = pytest.importorskip("pgserver")
    try:
        server = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as exc:  # binaries missing or failed to start on this platform
        pytest.skip(f"embedded Postgres unavailable: {type(exc).__name__}")
    yield server
    server.cleanup()


@pytest.fixture
def pg_url(_pg_server: Any) -> Iterator[str]:
    """A fresh, empty Postgres database for one test; dropped afterwards."""
    import psycopg

    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = _pg_server.get_uri()
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"create database {name}")
    from urllib.parse import quote

    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(admin)
    query = f"host={quote(str(info['host']), safe='')}&port={info.get('port', 5432)}"
    yield f"postgresql://{info.get('user', 'postgres')}@/{name}?{query}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"drop database if exists {name} with (force)")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--demo-db",
        choices=("sqlite", "postgres"),
        default="sqlite",
        help="database for the demo server tests (postgres = embedded, migrated, per test)",
    )


@pytest.fixture(autouse=True)
def demo_database(request: pytest.FixtureRequest, no_real_keys: None) -> None:
    """With --demo-db postgres, each demo test (API and store) gets a fresh migrated database."""
    if request.config.getoption("--demo-db") != "postgres":
        return
    name = request.node.module.__name__.split(".")[-1]
    if not name.startswith("test_demo_") or name == "test_demo_db":
        return
    if request.node.get_closest_marker("sqlite_only"):
        pytest.skip("checks the SQLite file itself")
    from demo_server import migrate

    url: str = request.getfixturevalue("pg_url")
    migrate.migrate(url)
    request.getfixturevalue("monkeypatch").setenv("DEMO_DATABASE_URL", url)
