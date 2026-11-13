"""Synthetic patches in the lake: synthetic/<gap_id>/seed=<n>/{incidents,anomalies}.parquet plus
a manifest. Never under bronze (nothing was fetched) and write-once, like bronze: a seed is
regenerated under a new seed, not overwritten.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from campus_safety.lake.parquet import Columns, write_parquet
from campus_safety.lake.storage import Lake
from campus_safety.synthetic.generate import Anomaly, SyntheticIncident
from campus_safety.synthetic.profile import Profile

INCIDENTS: Columns = (
    ("gap_id", "VARCHAR"),
    ("seed", "BIGINT"),
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),  # UTC, when generated
    ("source_ref", "VARCHAR"),  # lake key of the parquet file
    ("n", "INTEGER"),
    ("case_number", "VARCHAR"),
    ("occurred_at", "TIMESTAMP"),  # local wall time
    ("incident_type", "VARCHAR"),
    ("severity", "VARCHAR"),
    ("location", "VARCHAR"),
    ("location_type", "VARCHAR"),
    ("zone_id", "VARCHAR"),
    ("anomaly_id", "VARCHAR"),
    ("event_night", "BOOLEAN"),
)
ANOMALIES: Columns = (
    ("gap_id", "VARCHAR"),
    ("seed", "BIGINT"),
    ("anomaly_id", "VARCHAR"),
    ("zone_id", "VARCHAR"),
    ("start_at", "TIMESTAMP"),
    ("end_at", "TIMESTAMP"),
    ("multiplier", "DOUBLE"),
    ("kind", "VARCHAR"),
)
GAP_REGISTER: Columns = (
    ("gap_id", "VARCHAR"),
    ("source", "VARCHAR"),
    ("start", "DATE"),
    ("end", "DATE"),
    ("fields", "VARCHAR"),
    ("reason", "VARCHAR"),
    ("closing_source", "VARCHAR"),
)
TABLES: dict[str, Columns] = {
    "synthetic_incidents": INCIDENTS,
    "synthetic_anomalies": ANOMALIES,
    "gap_register": GAP_REGISTER,
}


@dataclass(frozen=True)
class Patch:
    gap_id: str
    seed: int
    run_id: str
    generated_at: datetime
    incidents: int
    anomalies: int
    profile_origin: str
    yearly_total: float


def prefix(gap_id: str, seed: int) -> str:
    return f"synthetic/{gap_id}/seed={seed}"


def write(
    lake: Lake,
    work: Path,
    gap_id: str,
    seed: int,
    run_id: str,
    incidents: list[SyntheticIncident],
    anomalies: list[Anomaly],
    profile: Profile,
    now: datetime | None = None,
) -> Patch:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    key = f"{prefix(gap_id, seed)}/incidents.parquet"
    stamp = now.replace(tzinfo=None)
    rows = [
        (
            gap_id,
            seed,
            run_id,
            stamp,
            key,
            i.n,
            i.case_number,
            i.occurred_at,
            i.incident_type,
            i.severity,
            i.location,
            i.location_type,
            i.zone_id,
            i.anomaly_id,
            i.event_night,
        )
        for i in incidents
    ]
    work.mkdir(parents=True, exist_ok=True)
    write_parquet(work / "incidents.parquet", INCIDENTS, rows)
    write_parquet(
        work / "anomalies.parquet",
        ANOMALIES,
        [
            (gap_id, seed, a.anomaly_id, a.zone_id, a.start, a.end, a.multiplier, a.kind)
            for a in anomalies
        ],
    )
    patch = Patch(
        gap_id,
        seed,
        run_id,
        now,
        len(incidents),
        len(anomalies),
        profile.origin,
        profile.yearly_total,
    )
    lake.create(key, (work / "incidents.parquet").read_bytes())
    lake.create(
        f"{prefix(gap_id, seed)}/anomalies.parquet", (work / "anomalies.parquet").read_bytes()
    )
    lake.create(
        f"{prefix(gap_id, seed)}/manifest.json",
        json.dumps(
            {**patch.__dict__, "generated_at": now.isoformat()}, indent=2, sort_keys=True
        ).encode(),
    )
    return patch


def patches(lake: Lake) -> list[Patch]:
    found = []
    for key in lake.keys("synthetic/"):
        if key.endswith("/manifest.json"):
            fields = json.loads(lake.get(key))
            fields["generated_at"] = datetime.fromisoformat(fields["generated_at"])
            found.append(Patch(**fields))
    return sorted(found, key=lambda p: (p.gap_id, p.seed))


def stage(lake: Lake, staging: Path) -> list[tuple[str, Path]]:
    """Copy every patch's parquet files into the staging folder; returns (lake key, path)."""
    published = []
    for table, name in (("synthetic_incidents", "incidents"), ("synthetic_anomalies", "anomalies")):
        for key in lake.keys("synthetic/"):
            if not key.endswith(f"/{name}.parquet"):
                continue
            gap_id, seed = key.split("/")[1], key.split("/")[2].removeprefix("seed=")
            path = staging / table / f"{gap_id}_{seed}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(lake.get(key))
            with duckdb.connect() as con:  # a corrupt or foreign file must not reach dbt
                con.execute("SELECT count(*) FROM read_parquet($p)", {"p": str(path)})
            published.append((key, path))
    return published
