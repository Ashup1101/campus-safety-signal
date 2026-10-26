"""Raw page snapshots and the SQLite incident store, both under the local data dir.

The database is derived: `iu-crime-log rebuild` recreates it from the snapshots, so a parser
fix can be replayed over every page ever fetched.
"""

import gzip
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from campus_safety.iu_crime_log.classify import geocodable
from campus_safety.iu_crime_log.parse import CrimeLog, Incident

DB_NAME = "iu_crime_log.sqlite3"
_SNAPSHOTS = Path("raw", "iu_crime_log")
_STAMP = "%Y%m%dT%H%M%SZ"
_SUFFIX = ".html.gz"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    fetched_at TEXT NOT NULL,  -- UTC
    snapshot TEXT NOT NULL,  -- relative to the data dir
    sha256 TEXT NOT NULL,  -- of the uncompressed page
    campus TEXT NOT NULL,
    window_start TEXT NOT NULL,  -- the page's own date range, to learn its update cadence
    window_end TEXT NOT NULL,
    records INTEGER NOT NULL,
    new_records INTEGER NOT NULL,
    changed_records INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents (
    case_number TEXT NOT NULL,
    offense TEXT NOT NULL,
    offense_count INTEGER NOT NULL,
    date_reported TEXT NOT NULL,
    occurred_from TEXT,  -- local wall time, no offset
    occurred_to TEXT,
    location TEXT NOT NULL,
    location_type TEXT NOT NULL,
    geocodable INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    severity TEXT NOT NULL,
    sensitive INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (case_number, offense)
);
-- A row when an incident first appears and one per later change, so a disposition moving
-- from OPEN CASE to SUSPECT ARRESTED keeps both.
CREATE TABLE IF NOT EXISTS incident_history (
    case_number TEXT NOT NULL,
    offense TEXT NOT NULL,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    observed_at TEXT NOT NULL,
    offense_count INTEGER NOT NULL,
    date_reported TEXT NOT NULL,
    occurred_from TEXT,
    occurred_to TEXT,
    location TEXT NOT NULL,
    disposition TEXT NOT NULL,
    PRIMARY KEY (case_number, offense, run_id)
);
"""

_TRACKED = (
    "offense_count",
    "date_reported",
    "occurred_from",
    "occurred_to",
    "location",
    "disposition",
)
_CURRENT = """
SELECT offense_count, date_reported, occurred_from, occurred_to, location, disposition
FROM incidents WHERE case_number = :case_number AND offense = :offense
"""
_INSERT_HISTORY = """
INSERT INTO incident_history (case_number, offense, run_id, observed_at, offense_count,
    date_reported, occurred_from, occurred_to, location, disposition)
VALUES (:case_number, :offense, :run_id, :seen, :offense_count, :date_reported,
    :occurred_from, :occurred_to, :location, :disposition)
"""
_UPSERT = """
INSERT INTO incidents (case_number, offense, offense_count, date_reported, occurred_from,
    occurred_to, location, location_type, geocodable, disposition, severity, sensitive,
    first_seen, last_seen)
VALUES (:case_number, :offense, :offense_count, :date_reported, :occurred_from, :occurred_to,
    :location, :location_type, :geocodable, :disposition, :severity, :sensitive, :seen, :seen)
ON CONFLICT (case_number, offense) DO UPDATE SET
    offense_count = excluded.offense_count,
    date_reported = excluded.date_reported,
    occurred_from = excluded.occurred_from,
    occurred_to = excluded.occurred_to,
    location = excluded.location,
    location_type = excluded.location_type,
    geocodable = excluded.geocodable,
    disposition = excluded.disposition,
    severity = excluded.severity,
    sensitive = excluded.sensitive,
    last_seen = excluded.last_seen
"""


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    records: int
    new: int
    changed: int


def write_snapshot(data_dir: Path, body: bytes, fetched_at: datetime) -> Path:
    stamp = fetched_at.astimezone(UTC)
    path = data_dir / _SNAPSHOTS / f"{stamp:%Y}" / f"{stamp:{_STAMP}}{_SUFFIX}"
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial")
    partial.write_bytes(gzip.compress(body, mtime=0))
    partial.replace(path)
    return path


def read_snapshot(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def snapshot_time(path: Path) -> datetime:
    return datetime.strptime(path.name.removesuffix(_SUFFIX), _STAMP).replace(tzinfo=UTC)


def list_snapshots(data_dir: Path) -> list[Path]:
    return sorted((data_dir / _SNAPSHOTS).glob(f"*/*{_SUFFIX}"), key=lambda path: path.name)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def ingest(
    conn: sqlite3.Connection, log: CrimeLog, *, fetched_at: datetime, snapshot: str, sha256: str
) -> RunSummary:
    """Upsert one page's incidents. Snapshots must be ingested oldest first."""
    seen = fetched_at.astimezone(UTC).isoformat(timespec="seconds")
    new = changed = 0
    with conn:
        cursor = conn.execute(
            "INSERT INTO runs (fetched_at, snapshot, sha256, campus, window_start, window_end,"
            " records, new_records, changed_records) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (
                seen,
                snapshot,
                sha256,
                log.campus,
                log.window_start.isoformat(),
                log.window_end.isoformat(),
                len(log.incidents),
            ),
        )
        run_id = cursor.lastrowid
        if run_id is None:
            raise RuntimeError("runs insert returned no id")
        for incident in log.incidents:
            values = {**_columns(incident), "seen": seen, "run_id": run_id}
            current = conn.execute(_CURRENT, values).fetchone()
            if current is None or tuple(current) != tuple(values[c] for c in _TRACKED):
                conn.execute(_INSERT_HISTORY, values)
                if current is None:
                    new += 1
                else:
                    changed += 1
            conn.execute(_UPSERT, values)
        conn.execute(
            "UPDATE runs SET new_records = ?, changed_records = ? WHERE id = ?",
            (new, changed, run_id),
        )
    return RunSummary(run_id=run_id, records=len(log.incidents), new=new, changed=changed)


def _columns(incident: Incident) -> dict[str, object]:
    return {
        "case_number": incident.case_number,
        "offense": incident.offense,
        "offense_count": incident.offense_count,
        "date_reported": incident.date_reported.isoformat(),
        "occurred_from": _iso(incident.occurred_from),
        "occurred_to": _iso(incident.occurred_to),
        "location": incident.location,
        "location_type": incident.location_type.value,
        "geocodable": geocodable(incident.location_type),
        "disposition": incident.disposition,
        "severity": incident.severity.value,
        "sensitive": incident.sensitive,
    }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
