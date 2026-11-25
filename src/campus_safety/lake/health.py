"""Source health for the IUPD console, from what the lake already stores.

Per source: the newest stored copy (bronze manifest), how many copies exist, and its state:
- never: nothing stored yet;
- failing: the newest copy was stored with an HTTP error, or (crime log) did not parse;
- stale: no new copy within the source's expected cadence (configs/sources.yaml);
- fresh: otherwise.
Error kinds only (parse_error, http_<status>), never page text. A fetch that failed and stored
nothing is not visible here: it leaves the newest copy older, so the source turns stale.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "sources.yaml"
PARSED = {"iu_crime_log"}  # sources whose run rows record whether the newest copy parsed


@dataclass(frozen=True)
class Cadence:
    source: str
    label: str
    expected_hours: int


def load(path: Path = CONFIG) -> list[Cadence]:
    entries = (yaml.safe_load(path.read_text()) or {}).get("sources") or {}
    found = []
    for source, entry in entries.items():
        hours = int(entry.get("expected_hours") or 0)
        if hours <= 0:
            raise ValueError(f"{source}: expected_hours must be a positive number of hours")
        found.append(Cadence(str(source), str(entry.get("label") or source), hours))
    return found


def _parse_error(lake: Lake, manifest: bronze.Manifest) -> bool:
    """Whether the transform's run row for this snapshot recorded a parse error."""
    folder, _, name = manifest.key.rpartition("/")
    key = (
        f"silver/iu_crime_log_runs/{folder.split('/')[1]}/{folder.rpartition('/')[2]}"
        f"/{name.split('.', 1)[0]}.parquet"
    )
    if key not in lake.keys(key.rpartition("/")[0] + "/"):
        return False  # not transformed yet: nothing known
    body = lake.get(key)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "run.parquet"
        local.write_bytes(body)
        with duckdb.connect(config={"memory_limit": "1GB", "threads": 2}) as con:
            found = con.execute(
                "SELECT count(*) FROM read_parquet($p) WHERE parse_error IS NOT NULL",
                {"p": str(local)},
            ).fetchone()
    return bool(found and found[0])


def state(
    newest: datetime | None, expected_hours: int, error_kind: str | None, now: datetime
) -> str:
    if newest is None:
        return "never"
    if error_kind:
        return "failing"
    return "stale" if now - newest > timedelta(hours=expected_hours) else "fresh"


def report(lake: Lake, cadences: Sequence[Cadence], now: datetime) -> list[dict[str, Any]]:
    rows = []
    for cadence in cadences:
        stored = bronze.manifests(lake, cadence.source)
        newest = stored[-1] if stored else None
        error_kind = None
        if newest is not None and (newest.http_status or 0) >= 400:
            error_kind = f"http_{newest.http_status}"
        elif newest is not None and cadence.source in PARSED and _parse_error(lake, newest):
            error_kind = "parse_error"
        fetched = newest.fetched_at if newest else None
        rows.append(
            {
                "source": cadence.source,
                "label": cadence.label,
                "expected_hours": cadence.expected_hours,
                "last_stored_at": fetched.isoformat() if fetched else None,
                "copies": len(stored),
                "state": state(fetched, cadence.expected_hours, error_kind, now),
                "error_kind": error_kind,
            }
        )
    return rows
