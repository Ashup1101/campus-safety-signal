"""Silver rows for BPD calls for service: one observation per call per pull, plus pull metadata.

Pages are read by DuckDB straight from the raw JSON (650k rows do not go through Python), with
the columns pinned so a renamed or missing field becomes NULL instead of a new schema.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from campus_safety.lake.bronze import Manifest

OBSERVATIONS = (
    ("dataset", "VARCHAR"),
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("pull_id", "VARCHAR"),  # one pull spans many pages; run_id is <pull_id>-pNNNN
    ("ingested_at", "TIMESTAMP"),  # UTC
    ("observed_at", "TIMESTAMP"),  # UTC
    ("case_number", "VARCHAR"),
    ("called_at", "TIMESTAMP"),  # local wall time, as published
    ("nature", "VARCHAR"),
    ("district", "VARCHAR"),
    ("agency", "VARCHAR"),
    ("report", "VARCHAR"),
)
METADATA = (
    ("pull_id", "VARCHAR"),
    ("source_ref", "VARCHAR"),
    ("pulled_at", "TIMESTAMP"),  # UTC
    ("rows_updated_at", "TIMESTAMP"),  # UTC, the portal's own last refresh
)
# Only these fields are read, with fixed types; anything else in the page is ignored.
_STAGE_SQL = (
    "COPY ("
    " SELECT $dataset AS dataset, $source_ref AS source_ref, $run_id AS run_id,"
    " $pull_id AS pull_id, $ingested_at::TIMESTAMP AS ingested_at,"
    " $observed_at::TIMESTAMP AS observed_at, case_number,"
    " try_cast(datetime AS TIMESTAMP) AS called_at, nature, district, agency, report"
    " FROM read_json($src, format = 'array', columns = {"
    "case_number: 'VARCHAR', datetime: 'VARCHAR', nature: 'VARCHAR',"
    " district: 'VARCHAR', agency: 'VARCHAR', report: 'VARCHAR'})"
    ") TO $dst (FORMAT parquet)"
)


def _utc(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(tzinfo=None)


def pull_id(manifest: Manifest) -> str:
    return manifest.run_id.rsplit("-", 1)[0]


def stage_page(manifest: Manifest, body: bytes, raw_dir: Path, target: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = raw_dir / f"{target.stem}.json"
    raw.write_bytes(body)
    params = {
        "src": str(raw),
        "dst": str(target),
        "dataset": manifest.source,
        "source_ref": manifest.key,
        "run_id": manifest.run_id,
        "pull_id": pull_id(manifest),
        "ingested_at": _utc(manifest.fetched_at),
        "observed_at": _utc(manifest.observed_at),
    }
    with duckdb.connect() as con:
        con.execute(_STAGE_SQL, params)
    raw.unlink()


def metadata_row(manifest: Manifest, body: bytes) -> tuple[object, ...]:
    updated = json.loads(body).get("rowsUpdatedAt")
    return (
        pull_id(manifest),
        manifest.key,
        _utc(manifest.fetched_at),
        datetime.fromtimestamp(updated, UTC).replace(tzinfo=None) if updated else None,
    )
