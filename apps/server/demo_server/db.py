"""One small database layer for the demo store: SQLite (default) or Postgres (psycopg pool).

Store methods write plain SQL with `?` placeholders and portable `on conflict` clauses; this layer
converts placeholders for Postgres and gives each thread its own connection during a transaction.
The connection string is a secret: it is never logged or put in error messages.
"""

import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Dialect = Literal["sqlite", "postgres"]
POSTGRES_PREFIXES = ("postgres://", "postgresql://")


class IntegrityError(sqlite3.IntegrityError):
    """A duplicate key or broken reference, raised the same way by both backends."""


def is_postgres_url(url: str | None) -> bool:
    return bool(url) and str(url).startswith(POSTGRES_PREFIXES)


def to_postgres(sql: str) -> str:
    """`?` -> `%s`; a literal `%` (as in `like '%x'`) must be doubled for psycopg."""
    return sql.replace("%", "%%").replace("?", "%s")


def _columns(columns: Sequence[str]) -> str:
    for name in columns:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            raise ValueError("bad column name")
    return ", ".join(columns)


def upsert_sql(table: str, columns: Sequence[str], key: Sequence[str]) -> str:
    """Insert, or replace the non-key columns of the row with the same key (both dialects)."""
    rest = [c for c in columns if c not in key]
    action = (
        "do update set " + ", ".join(f"{c} = excluded.{c}" for c in rest) if rest else "do nothing"
    )
    marks = ", ".join("?" for _ in columns)
    return (
        f"insert into {_columns([table])} ({_columns(columns)}) values ({marks})"  # noqa: S608
        f" on conflict ({_columns(key)}) {action}"
    )


def insert_ignore_sql(table: str, columns: Sequence[str]) -> str:
    """Insert unless any unique key already holds the row (both dialects)."""
    marks = ", ".join("?" for _ in columns)
    return (
        f"insert into {_columns([table])} ({_columns(columns)}) values ({marks})"  # noqa: S608
        " on conflict do nothing"
    )


@dataclass
class Result:
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    rowcount: int = 0

    def fetchone(self) -> Any:  # a row tuple or None, typed loosely like sqlite3
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        return iter(self.rows)


class Database:
    """`execute` outside `with db:` commits on its own; inside, the block commits or rolls back."""

    dialect: Dialect

    def __init__(self, target: Path | str) -> None:
        self._local = threading.local()
        if is_postgres_url(str(target)):
            from psycopg_pool import ConnectionPool

            self.dialect = "postgres"
            self._pool: Any = ConnectionPool(
                str(target), min_size=1, max_size=4, open=True, name="demo-store"
            )
            self._sqlite: sqlite3.Connection | None = None
        else:
            self.dialect = "sqlite"
            self._pool = None
            # Autocommit; explicit begin/commit in `transaction`. One connection, one lock.
            self._sqlite = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
            self._sqlite_lock = threading.RLock()

    def _depth(self) -> int:
        return int(getattr(self._local, "depth", 0))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._depth():  # nested: the outermost block decides
            self._local.depth += 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return
        with ExitStack() as stack:
            if self._sqlite is not None:
                stack.enter_context(self._sqlite_lock)
                self._sqlite.execute("begin")
            else:
                conn = stack.enter_context(self._pool.connection())
                stack.enter_context(conn.transaction())
                self._local.conn = conn
            self._local.depth = 1
            try:
                yield
            except BaseException:
                if self._sqlite is not None:
                    self._sqlite.execute("rollback")
                raise
            else:
                if self._sqlite is not None:
                    self._sqlite.execute("commit")
            finally:
                self._local.depth = 0
                self._local.conn = None

    def __enter__(self) -> "Database":
        stack = self._local.__dict__.setdefault("blocks", [])
        block = self.transaction()
        block.__enter__()
        stack.append(block)
        return self

    def __exit__(self, *exc: Any) -> None:
        self._local.blocks.pop().__exit__(*exc)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        if self._sqlite is not None:
            with self._sqlite_lock:
                try:
                    cursor = self._sqlite.execute(sql, tuple(params))
                except sqlite3.IntegrityError as exc:
                    raise IntegrityError(str(exc)) from exc
                rows = cursor.fetchall() if cursor.description else []
                return Result(rows, cursor.rowcount)
        conn = getattr(self._local, "conn", None) if self._depth() else None
        if conn is not None:
            return self._pg_run(conn, sql, params)
        with self._pool.connection() as conn:
            return self._pg_run(conn, sql, params)

    @staticmethod
    def _pg_run(conn: Any, sql: str, params: Sequence[Any]) -> Result:
        import psycopg

        with conn.cursor() as cursor:
            try:
                cursor.execute(to_postgres(sql), tuple(params))
            except psycopg.IntegrityError as exc:
                raise IntegrityError(type(exc).__name__) from exc
            rows = cursor.fetchall() if cursor.description else []
            return Result([tuple(r) for r in rows], cursor.rowcount)

    def executescript(self, sql: str) -> None:
        if self._sqlite is not None:
            with self._sqlite_lock:
                self._sqlite.executescript(sql)
            return
        with self._pool.connection() as conn:
            conn.execute(sql)  # trusted, checked-in migration text

    def close(self) -> None:
        if self._sqlite is not None:
            self._sqlite.close()
        else:
            self._pool.close()
