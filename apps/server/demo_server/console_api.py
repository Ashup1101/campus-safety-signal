"""IUPD console API (console role only, enforced by the caller's dependency). Every view that mixes
real and synthetic data is real-only unless asked (real_only=false); counts and dates only, never
records, names or free text."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, Query

from campus_safety import events, gaps
from campus_safety.lake import health
from campus_safety.lake.storage import open_lake
from campus_safety.models import registry
from demo_server import forecasts, metrics, pilot
from demo_server.store import Store

CONFIG: dict[str, str | bool | int | float | list[str]] = {"memory_limit": "1GB", "threads": 2}
SYNTHETIC = ("synthetic_rows", "synthetic_seeds", "planted_anomalies")
RealOnly = Annotated[bool, Query()]
MODELS = (
    ("t1", "Tonight forecast (calls per police zone)"),
    ("t2", "News relevance (which items reach the language model)"),
    ("t3", "Crime-log fallback reader"),
    ("t4", "Prompt-injection screen"),
)


@dataclass(frozen=True)
class _T1Run:
    card: dict[str, Any]


def t1_run(lake: Any) -> _T1Run | None:
    """The newest imported T1 run (t1/<run_id>/), shaped like a registry run."""
    stamps = [
        (str(json.loads(lake.get(k))["imported_at"]), k.removesuffix("import.json"))
        for k in lake.keys("t1/")
        if k.endswith("/import.json")
    ]
    if not stamps:
        return None
    _, prefix = max(stamps)
    return _T1Run(json.loads(lake.get(prefix + "scorecard.json")))


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
        except (
            duckdb.CatalogException,
            duckdb.BinderException,
            duckdb.IOException,
        ):  # missing, older or locked (a transform is writing)
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

    @app.get("/api/console/database")
    def console_database(_: Console) -> dict[str, Any]:
        """SQLite on this laptop or Postgres with its schema version (no host or credentials)."""
        return store.database()

    @app.get("/api/console/forecasts")
    def console_forecasts(_: Console) -> dict[str, Any]:
        rows = _rows(
            warehouse,
            "select zonecode, night, expected, level, method, reason, run_id from gold.tonight"
            " where \"window\" = 'late_night' order by night, zonecode",
        )
        card = forecasts.scorecard(open_lake(lake_uri), rows[0]["run_id"]) if rows else None
        return forecasts.build(rows, card, events.load(), events.night_of(datetime.now(UTC)))

    @app.get("/api/console/zones")
    def console_zones(_: Console) -> dict[str, Any]:
        """Polygons of the police zones the newest forecast covers (GeoJSON), for the map."""
        found = _rows(
            warehouse,
            "select zonecode, geometry from silver.geo_law_zones where geometry is not null"
            " and zonecode in (select zonecode from gold.tonight) order by zonecode",
        )
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"zonecode": row["zonecode"]},
                    "geometry": json.loads(row["geometry"]),
                }
                for row in found
            ],
        }

    @app.get("/api/console/trends")
    def console_trends(_: Console) -> list[dict[str, Any]]:
        """Calls for service per week and zone vs the same week a year earlier (counts only)."""
        return _rows(
            warehouse,
            "select week, zonecode, calls, calls_last_year from gold.console_weekly_trends"
            " order by zonecode, week",
        )

    @app.get("/api/console/models")
    def console_models(_: Console) -> list[dict[str, Any]]:
        """One card per model (T1 forecast, T2 relevance, T3 fallback, T4 injection screen):
        which method is in use, in words, with the newest run's scores."""
        lake = open_lake(lake_uri)
        cards = []
        for name, what in MODELS:
            run = t1_run(lake) if name == "t1" else registry.latest(lake, name)
            card = run.card if run is not None else None
            using = card is not None and card.get("method") == "model"
            trained = card is not None and (card.get("scores") or {}).get("model") is not None
            words = (
                "Using the model: it beat the rules on its test"
                if using
                else "Using rules: the model lost on its test"
                if trained
                else "Using rules: this run trained no model"
                if card is not None
                else "Using rules: no model imported yet"
            )
            cards.append(
                {
                    "name": name,
                    "what": what,
                    "words": words,
                    "run_id": card.get("run_id") if card else None,
                    "trained_at": card.get("trained_at") if card else None,
                    "scores": card.get("scores", {}) if card else {},
                }
            )
        return cards

    @app.get("/api/console/pilot")
    def console_pilot(_: Console) -> dict[str, Any]:
        """Pilot numbers on one page: counts, medians and averages, never a person."""
        return pilot.metrics(store, datetime.now(UTC))
