"""patterns: build the gold pattern tables from the warehouse (run) or score the anomaly
detector against a synthetic patch's planted spikes (score). Reads the warehouse read-only
after `make transform`; writes gold/<table>.parquet to the lake. Counts only in the log."""

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from botocore.exceptions import BotoCoreError, ClientError

from campus_safety import events
from campus_safety.lake.parquet import Columns, write_parquet
from campus_safety.lake.storage import LakeConfigError, open_lake
from campus_safety.patterns import baselines
from campus_safety.patterns.levels import Observation, levels

log = logging.getLogger("patterns")
WAREHOUSE = Path("data", "warehouse", "warehouse.duckdb")
DUCKDB_CONFIG: dict[str, str | bool | int | float | list[str]] = {
    "memory_limit": "1GB",
    "threads": 2,
}
REAL_SQL = (
    "select location_text, occurred_from, incident_type, severity_tier from gold.incidents_real"
    " where not is_sensitive and occurred_from is not null and location_text is not null"
    " and location_type in ('place', 'street_segment', 'block')"
)
SYNTHETIC_SQL = (
    "select location, occurred_at, incident_type, severity from silver.synthetic_incidents"
    " where gap_id = $gap and seed = $seed"
)
SPIKES_SQL = (
    "select zone_id, start_at, end_at from silver.synthetic_anomalies"
    " where gap_id = $gap and seed = $seed and kind = 'spike'"
)
TABLES: dict[str, Columns] = {
    "activity_levels": (
        ("place", "VARCHAR"),
        ("window", "VARCHAR"),
        ("level", "VARCHAR"),
        ("reason", "VARCHAR"),
        ("incidents", "INTEGER"),
        ("serious", "INTEGER"),
        ("as_of", "TIMESTAMP"),
    ),
    "anomalies": (
        ("place", "VARCHAR"),
        ("night", "DATE"),
        ("observed", "INTEGER"),
        ("expected", "DOUBLE"),
        ("p_value", "DOUBLE"),
        ("event_night", "BOOLEAN"),
        ("as_of", "TIMESTAMP"),
    ),
    "forecasts": (
        ("place", "VARCHAR"),
        ("night", "DATE"),
        ("expected", "DOUBLE"),
        ("event_night", "BOOLEAN"),
        ("as_of", "TIMESTAMP"),
    ),
    "baselines": (
        ("place", "VARCHAR"),
        ("weekday", "INTEGER"),
        ("mean_per_night", "DOUBLE"),
        ("as_of", "TIMESTAMP"),
    ),
}


def observations(
    warehouse: Path, sql: str, params: dict[str, object] | None = None
) -> list[Observation]:
    if not warehouse.exists():
        raise LakeConfigError(f"no warehouse at {warehouse}; run make transform first")
    with duckdb.connect(str(warehouse), read_only=True, config=DUCKDB_CONFIG) as con:
        rows = con.execute(sql, params or {}).fetchall()
    return [Observation(str(place), at, str(kind), tier) for place, at, kind, tier in rows]


def run(warehouse: Path, work: Path, as_of: datetime) -> int:
    found = observations(warehouse, REAL_SQL)
    nights = events.event_nights()
    stamp = as_of.astimezone(UTC).replace(tzinfo=None)
    local_now = events.local(as_of)
    tables: dict[str, list[tuple[object, ...]]] = {
        "activity_levels": [
            (r.place, r.window, r.level, r.reason, r.incidents, r.serious, stamp)
            for r in levels(found, local_now, nights)
        ],
        "anomalies": [
            (a.place, a.night, a.observed, a.expected, a.p_value, a.event_night, stamp)
            for a in baselines.detect(found, nights, local_now)
        ],
        "forecasts": [
            (f.place, f.night, f.expected, f.event_night, stamp)
            for f in baselines.forecast(found, nights, local_now)
        ],
        "baselines": [
            (b.place, b.weekday, b.mean_per_night, stamp)
            for b in baselines.baselines(found, local_now)
        ],
    }
    lake = open_lake(os.environ.get("LAKE_URI"))
    work.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        path = work / f"{name}.parquet"
        write_parquet(path, TABLES[name], rows)
        lake.put(f"gold/{name}.parquet", path.read_bytes())
    high = sum(r[2] == "high" for r in tables["activity_levels"])
    log.info(
        "%d observations -> %d level rows (%d high), %d anomalies, %d forecast rows, %d baselines",
        len(found),
        len(tables["activity_levels"]),
        high,
        len(tables["anomalies"]),
        len(tables["forecasts"]),
        len(tables["baselines"]),
    )
    return 0


def score(warehouse: Path, gap_id: str, seed: int) -> int:
    params: dict[str, object] = {"gap": gap_id, "seed": seed}
    found = observations(warehouse, SYNTHETIC_SQL, params)
    if not found:
        log.error("no synthetic rows for %s seed %d in the warehouse", gap_id, seed)
        return 1
    with duckdb.connect(str(warehouse), read_only=True, config=DUCKDB_CONFIG) as con:
        spikes = [(str(z), s, e) for z, s, e in con.execute(SPIKES_SQL, params).fetchall()]
    last = max(o.occurred_at for o in found)
    first = min(o.occurred_at for o in found).date()
    detected = baselines.detect(found, events.event_nights(), last, since=first)
    result = baselines.score(detected, spikes)
    log.info(
        "%s seed %d: %d planted spikes, %d detected nights, %d spikes found, %d false alarms,"
        " precision %.2f, recall %.2f",
        gap_id,
        seed,
        result.planted,
        result.detected,
        result.hits,
        result.false_alarms,
        result.precision,
        result.recall,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patterns", description=__doc__)
    parser.add_argument("--warehouse", type=Path, default=WAREHOUSE)
    parser.add_argument("--work-dir", type=Path, default=Path("data/patterns"))
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="levels, anomalies, forecasts, baselines -> gold")
    run_parser.add_argument("--as-of", type=datetime.fromisoformat, default=None)
    score_parser = commands.add_parser("score", help="detector precision/recall on a patch")
    score_parser.add_argument("gap_id")
    score_parser.add_argument("seed", type=int)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "score":
            return score(args.warehouse, args.gap_id, args.seed)
        as_of = args.as_of or datetime.now(UTC)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=events.LOCAL)
        return run(args.warehouse, args.work_dir, as_of)
    except (LakeConfigError, ClientError, BotoCoreError, duckdb.Error) as e:
        log.error("%s", e)
        return 1
