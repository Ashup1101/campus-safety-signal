"""`make transform`: replay all of bronze into silver and gold, end to end.

1. Stage every bronze object as Parquet: crime log snapshots (observations + one run row each),
   BPD call pages (observations) and their pull metadata.
2. dbt build in a local DuckDB warehouse: conform, derive history, enforce the contract, test,
   and build the gold reports (coverage, BPD audit).
3. Publish the staged files and the silver and gold tables to the lake.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from campus_safety.bpd_cfs import pull as bpd_pull
from campus_safety.bpd_cfs import silver as bpd_silver
from campus_safety.calibration import bps, doe
from campus_safety.iu_crime_log import backfill, silver
from campus_safety.iu_crime_log.classify import Severity
from campus_safety.iu_crime_log.legacy import parse_legacy_pdf
from campus_safety.iu_crime_log.parse import CrimeLog, Incident, ParseError, parse_crime_log
from campus_safety.lake import bronze
from campus_safety.lake.parquet import Columns, write_parquet
from campus_safety.lake.storage import Lake
from campus_safety.t3 import fallback

DBT_PROJECT = Path(__file__).resolve().parents[3] / "dbt"
CRIME_LOG_DATASETS = (silver.SOURCE, backfill.SOURCE)
STAGED_SCHEMAS: dict[str, Columns] = {
    "iu_crime_log_observations": silver.OBSERVATIONS,
    "iu_crime_log_runs": silver.RUNS,
    "bpd_cfs_observations": bpd_silver.OBSERVATIONS,
    "bpd_cfs_metadata": bpd_silver.METADATA,
    "calibration_clery_rows": doe.ROWS,
    "calibration_bpd_metric_rows": bps.ROWS,
}
PUBLISHED = (
    ("silver", "incidents"),
    ("silver", "incident_sources"),
    ("silver", "iu_crime_log_incidents"),
    ("silver", "iu_crime_log_incident_history"),
    ("silver", "bpd_calls_for_service"),
    ("silver", "calibration_clery"),
    ("silver", "calibration_bpd_monthly"),
    ("gold", "iu_crime_log_coverage"),
    ("gold", "bpd_cfs_audit"),
    ("gold", "bpd_cfs_rows_per_year"),
    ("gold", "bpd_cfs_nature_counts"),
    ("gold", "bpd_cfs_district_formats"),
    ("gold", "bpd_cfs_missing_days"),
    ("gold", "bpd_cfs_refresh_history"),
    ("gold", "calibration_bpd_cfs_check"),
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
    coverage: tuple[tuple[str, str, str, str, int], ...] = ()  # dataset, kind, start, end, days
    bpd_pages: int = 0
    bpd_audit: tuple[tuple[str, object], ...] = ()  # column, value from gold.bpd_cfs_audit
    calibration_files: int = 0
    calibration_errors: int = 0
    llm_recovered: int = 0  # incidents read by the LLM fallback (extractor=llm_fallback)


@dataclass
class _Staged:
    published: list[tuple[str, Path]]
    snapshots: int = 0
    parse_errors: int = 0
    bpd_pages: int = 0
    calibration_files: int = 0
    calibration_errors: int = 0
    llm_recovered: int = 0


def parse_snapshot(manifest: bronze.Manifest, body: bytes) -> CrimeLog:
    if manifest.key.endswith(".pdf.gz"):
        return parse_legacy_pdf(body)
    return parse_crime_log(body.decode("utf-8", errors="replace"))


def _lake_key(table: str, manifest: bronze.Manifest) -> tuple[str, str]:
    """Staging file name and published silver key for one bronze object."""
    folder, _, name = manifest.key.rpartition("/")
    dataset, partition = folder.split("/")[1], folder.rpartition("/")[2]
    stem = name.split(".", 1)[0]
    return f"{dataset}_{stem}.parquet", f"silver/{table}/{dataset}/{partition}/{stem}.parquet"


@dataclass(frozen=True)
class Extraction:
    """Rules only, or rules plus cached LLM answers for snapshots the rules could not read."""

    extractor: str = "rules"  # rules | llm_fallback
    cache_dir: Path | None = None
    verified: frozenset[tuple[str, str]] = frozenset()  # (case_number, offense) the owner checked


def _fallback_log(extraction: Extraction, manifest: bronze.Manifest) -> CrimeLog | None:
    if extraction.extractor != "llm_fallback" or extraction.cache_dir is None:
        return None
    unique: dict[tuple[str, str], Incident] = {}
    for incident in fallback.cached_incidents(extraction.cache_dir, manifest.sha256):
        unique.setdefault((incident.case_number, incident.offense), incident)
    if not unique:
        return None
    reported = [incident.date_reported for incident in unique.values()]
    return CrimeLog("Bloomington", min(reported), max(reported), tuple(unique.values()))


def _stage_crime_log(
    lake: Lake, staging: Path, staged: _Staged, extraction: Extraction
) -> set[str]:
    manifests = sorted(
        (m for dataset in CRIME_LOG_DATASETS for m in bronze.manifests(lake, dataset)),
        key=lambda m: (m.observed_at, m.key),
    )
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
            staged.parse_errors += 1
        observations = silver.observation_rows(log, manifest) if log else []
        recovered = None if log else _fallback_log(extraction, manifest)
        if recovered is not None:
            # Coverage stays rules-only: the run row keeps its parse error and no window.
            observations = silver.observation_rows(
                recovered, manifest, "llm_fallback", extraction.verified
            )
            staged.llm_recovered += len(recovered.incidents)
        for table, rows in (
            ("iu_crime_log_observations", observations),
            ("iu_crime_log_runs", [silver.run_row(manifest, log, error)]),
        ):
            name, key = _lake_key(table, manifest)
            write_parquet(staging / table / name, STAGED_SCHEMAS[table], rows)
            staged.published.append((key, staging / table / name))
    staged.snapshots += len(manifests)
    return unclassified


def _stage_bpd(lake: Lake, staging: Path, staged: _Staged) -> None:
    for manifest in bronze.manifests(lake, bpd_pull.SOURCE):
        name, key = _lake_key("bpd_cfs_observations", manifest)
        path = staging / "bpd_cfs_observations" / name
        bpd_silver.stage_page(manifest, bronze.read(lake, manifest), staging / "raw", path)
        staged.published.append((key, path))
        staged.bpd_pages += 1
    for manifest in bronze.manifests(lake, bpd_pull.METADATA_SOURCE):
        name, key = _lake_key("bpd_cfs_metadata", manifest)
        path = staging / "bpd_cfs_metadata" / name
        row = bpd_silver.metadata_row(manifest, bronze.read(lake, manifest))
        write_parquet(path, bpd_silver.METADATA, [row])
        staged.published.append((key, path))


def _stage_calibration(lake: Lake, staging: Path, staged: _Staged) -> None:
    for source, table, parse in (
        (doe.SOURCE, "calibration_clery_rows", doe.rows),
        (bps.SOURCE, "calibration_bpd_metric_rows", bps.rows),
    ):
        for manifest in bronze.manifests(lake, source):
            try:
                rows = parse(manifest, bronze.read(lake, manifest))
            except (ParseError, ValueError):
                staged.calibration_errors += 1
                continue
            name, key = _lake_key(table, manifest)
            write_parquet(staging / table / name, STAGED_SCHEMAS[table], rows)
            staged.published.append((key, staging / table / name))
            staged.calibration_files += 1


def transform(lake: Lake, work_dir: Path, extraction: Extraction | None = None) -> TransformSummary:
    extraction = extraction or Extraction()
    staging = work_dir / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staged = _Staged(published=[])
    unclassified = _stage_crime_log(lake, staging, staged, extraction)
    _stage_bpd(lake, staging, staged)
    _stage_calibration(lake, staging, staged)
    if not staged.snapshots and not staged.bpd_pages:
        raise TransformError(f"no crime log snapshots or BPD pages in bronze at {lake.uri}")
    for table, columns in STAGED_SCHEMAS.items():
        # dbt reads each table as a glob; an empty file keeps a not-yet-pulled source valid.
        if not (staging / table).is_dir():
            write_parquet(staging / table / "empty.parquet", columns, [])

    warehouse = work_dir / "warehouse.duckdb"
    _dbt_build(work_dir, staging, warehouse)

    exports = work_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(warehouse)) as con:
        for layer, table in PUBLISHED:
            path = exports / f"{layer}_{table}.parquet"
            con.execute(f"COPY {layer}.{table} TO $path (FORMAT parquet)", {"path": str(path)})
            staged.published.append((f"{layer}/{table}.parquet", path))
        incidents, cases = _one(
            con, "SELECT count(*), count(DISTINCT case_number) FROM silver.iu_crime_log_incidents"
        )
        (history_rows,) = _one(con, "SELECT count(*) FROM silver.iu_crime_log_incident_history")
        coverage = [
            (str(dataset), str(kind), str(start), str(end), int(days))
            for dataset, kind, start, end, days in con.execute(
                "SELECT * FROM gold.iu_crime_log_coverage ORDER BY dataset, range_start"
            ).fetchall()
        ]
        audit = con.execute("SELECT * FROM gold.bpd_cfs_audit")
        names = [str(column[0]) for column in audit.description]
        bpd_audit = tuple(zip(names, audit.fetchone() or (), strict=False))

    for key, path in staged.published:
        lake.put(key, path.read_bytes())
    return TransformSummary(
        staged.snapshots,
        staged.parse_errors,
        incidents,
        cases,
        history_rows,
        frozenset(unclassified),
        tuple(coverage),
        staged.bpd_pages,
        bpd_audit if staged.bpd_pages else (),
        staged.calibration_files,
        staged.calibration_errors,
        staged.llm_recovered,
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
