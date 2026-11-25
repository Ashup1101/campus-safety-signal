"""IUPD console API (console role only, enforced by the caller's dependency). Every view that mixes
real and synthetic data is real-only unless asked (real_only=false); counts and dates only, never
records, names or free text."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, Query

from campus_safety import gaps

CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
SYNTHETIC = ("synthetic_rows", "synthetic_seeds", "planted_anomalies")
RealOnly = Annotated[bool, Query()]


def _rows(warehouse: Path, sql: str) -> list[dict[str, Any]]:
    if not warehouse.exists():
        return []
    with duckdb.connect(str(warehouse), read_only=True, config=CONFIG) as con:
        try:
            cursor = con.execute(sql)
        except duckdb.CatalogException:
            return []
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def register(
    app: FastAPI, console: Callable[..., Any], warehouse: Path, register_file: Path
) -> None:
    Console = Annotated[Any, Depends(console)]

    @app.get("/api/console/gaps")
    def console_gaps(_: Console, real_only: RealOnly = True) -> list[dict[str, Any]]:
        reasons = {g.gap_id: g.reason for g in gaps.load(register_file)}
        found = []
        for row in _rows(warehouse, "select * from gold.gap_report order by span_start"):
            row = {k: v for k, v in row.items() if not (real_only and k in SYNTHETIC)}
            found.append({**row, "reason": reasons.get(str(row["gap_id"]), "")})
        return found
