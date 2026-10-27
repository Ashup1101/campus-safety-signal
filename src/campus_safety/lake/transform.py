"""`make transform`: replay all of bronze into silver, end to end.

1. Parse every bronze snapshot into staging Parquet (observations + one run row each).
2. dbt build in a local DuckDB warehouse: conform, derive history, enforce the contract, test.
3. Publish the staging files and silver tables under the lake's silver/ prefix.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from campus_safety.iu_crime_log import backfill, silver
from campus_safety.iu_crime_log.classify import Severity
from campus_safety.iu_crime_log.legacy import parse_legacy_pdf
from campus_safety.iu_crime_log.parse import CrimeLog, ParseError, parse_crime_log
from campus_safety.lake import bronze
from campus_safety.lake.parquet import write_parquet
from campus_safety.lake.storage import Lake

DBT_PROJECT = Path(__file__).resolve().parents[3] / "dbt"
CRIME_LOG_DATASETS = (silver.SOURCE, backfill.SOURCE)
SILVER_TABLES = (
    "incidents",
    "incident_sources",
    "iu_crime_log_incidents",
    "iu_crime_log_incident_history",
)


class TransformError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransformSummary:
    snapshots: int
    parse_errors: int
    incidents: int
    cases: int
    history_rows: int
    unclassified: frozenset[str]  # offense labels no severity rule matched; never logged


def parse_snapshot(manifest: bronze.Manifest, body: bytes) -> CrimeLog:
    if manifest.key.endswith(".pdf.gz"):
        return parse_legacy_pdf(body)
    return parse_crime_log(body.decode("utf-8", errors="replace"))


def transform(lake: Lake, work_dir: Path) -> TransformSummary:
    manifests = sorted(
        (m for dataset in CRIME_LOG_DATASETS for m in bronze.manifests(lake, dataset)),
        key=lambda m: (m.observed_at, m.key),
    )
    if not manifests:
        raise TransformError(f"no crime log snapshots in bronze at {lake.uri}")
    staging = work_dir / "staging"
    shutil.rmtree(staging, ignore_errors=True)

    published: list[tuple[str, Path]] = []
    parse_errors = 0
    unclassified: set[str] = set()
    for manifest in manifests:
        log: CrimeLog | None = None
        error: str | None = None
        try:
            log = parse_snapshot(manifest, bronze.read(lake, manifest))
            unclassified |= {
                i.offense for i in log.incidents if i.severity is Severity.UNCLASSIFIED
            }
        except ParseError as e:
            error = str(e)
            parse_errors += 1
        folder, _, name = manifest.key.rpartition("/")
        dataset, partition = folder.split("/")[1], folder.rpartition("/")[2]
        stem = name.split(".", 1)[0]
        observations = silver.observation_rows(log, manifest) if log else []
        tables = (
            ("iu_crime_log_observations", silver.OBSERVATIONS, observations),
            ("iu_crime_log_runs", silver.RUNS, [silver.run_row(manifest, log, error)]),
        )
        for table, columns, rows in tables:
            path = staging / table / f"{dataset}_{stem}.parquet"
            write_parquet(path, columns, rows)
            published.append((f"silver/{table}/{dataset}/{partition}/{stem}.parquet", path))

    warehouse = work_dir / "warehouse.duckdb"
    _dbt_build(work_dir, staging, warehouse)

    exports = work_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(warehouse)) as con:
        for table in SILVER_TABLES:
            path = exports / f"{table}.parquet"
            con.execute(f"COPY silver.{table} TO $path (FORMAT parquet)", {"path": str(path)})
            published.append((f"silver/{table}.parquet", path))
        incidents, cases = _one(
            con, "SELECT count(*), count(DISTINCT case_number) FROM silver.iu_crime_log_incidents"
        )
        (history_rows,) = _one(con, "SELECT count(*) FROM silver.iu_crime_log_incident_history")

    for key, path in published:
        lake.put(key, path.read_bytes())
    return TransformSummary(
        len(manifests), parse_errors, incidents, cases, history_rows, frozenset(unclassified)
    )


def _one(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[int, ...]:
    row = con.execute(sql).fetchone()
    if row is None:
        raise TransformError(f"no result for {sql}")
    return tuple(int(value) for value in row)


def _dbt_build(work_dir: Path, staging: Path, warehouse: Path) -> None:
    from dbt.cli.main import dbtRunner

    os.environ["LAKE_STAGING_DIR"] = str(staging)
    os.environ["WAREHOUSE_PATH"] = str(warehouse)
    result = dbtRunner().invoke(
        [
            "build",
            "--quiet",
            "--project-dir",
            str(DBT_PROJECT),
            "--profiles-dir",
            str(DBT_PROJECT),
            "--target-path",
            str(work_dir / "dbt_target"),
            "--log-path",
            str(work_dir / "dbt_logs"),
        ]
    )
    if not result.success:
        raise TransformError(f"dbt build failed; details in {work_dir / 'dbt_logs'}")
