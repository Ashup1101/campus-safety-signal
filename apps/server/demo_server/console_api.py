"""IUPD console API (console role only, enforced by the caller's dependency). Every view that mixes
real and synthetic data is real-only unless asked (real_only=false); counts and dates only, never
records, names or free text."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, Query

from campus_safety import gaps
from campus_safety.lake import health
from campus_safety.lake.storage import open_lake
from demo_server import metrics
from demo_server.store import Store

CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
SYNTHETIC = ("synthetic_rows", "synthetic_seeds", "planted_anomalies")
RealOnly = Annotated[bool, Query()]
CALLS_NOTE = (
    "Calls for service are not crimes: a call is a request for police help, and many end with no"
    " report. IU log entries are recorded incidents. Only categories both sources name are shown."
)


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
    app: FastAPI,
    console: Callable[..., Any],
    warehouse: Path,
    register_file: Path,
    store: Store,
    lake_uri: str,
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

    @app.get("/api/console/cross-check")
    def console_cross_check(_: Console) -> dict[str, Any]:
        """Real data only (official log and city feed): no real_only switch needed."""
        return {
            "note": CALLS_NOTE,
            "rows": _rows(
                warehouse,
                "select month, zonecode, category, iu_count, bpd_count"
                " from gold.console_cross_check order by month, zonecode, category",
            ),
            "calibration": _rows(
                warehouse,
                "select * from gold.calibration_bpd_cfs_check order by period_year, period_month",
            ),
        }

    @app.get("/api/console/archive")
    def console_archive(_: Console) -> list[dict[str, Any]]:
        """Wayback captures of the IU log per year: listed, parsed, failed, not fetched."""
        return _rows(warehouse, "select * from gold.archive_coverage order by year")

    @app.get("/api/console/alert-metrics")
    def console_alert_metrics(
        _: Console, days: Annotated[int, Query(ge=1, le=365)] = 30
    ) -> dict[str, Any]:
        return metrics.alert_metrics(store, datetime.now(UTC), days)

    @app.get("/api/console/health")
    def console_health(_: Console) -> list[dict[str, Any]]:
        """Every configured source: fresh, stale, failing or never, with times (no page text)."""
        return health.report(open_lake(lake_uri), health.load(), datetime.now(UTC))
