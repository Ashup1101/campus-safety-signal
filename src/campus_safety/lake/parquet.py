"""Write rows to Parquet with an explicit schema, via DuckDB (transform dependency group)."""

from collections.abc import Sequence
from pathlib import Path

import duckdb

Columns = Sequence[tuple[str, str]]


def write_parquet(path: Path, columns: Columns, rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        # Column names and types are code constants, never data.
        schema = ", ".join(f'"{name}" {sql_type}' for name, sql_type in columns)
        con.execute(f"CREATE TABLE t ({schema})")
        if rows:
            marks = ", ".join("?" for _ in columns)
            con.executemany(f"INSERT INTO t VALUES ({marks})", rows)  # noqa: S608
        con.execute("COPY t TO $path (FORMAT parquet)", {"path": str(path)})
