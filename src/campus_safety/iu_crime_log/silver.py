"""Silver rows for the IU crime log: one observation per incident per bronze snapshot.

Observations are append-only facts ("this page, fetched then, listed this"). first_seen,
last_seen, and disposition history are derived from them in dbt, never stored as mutable state.
"""

from datetime import UTC, datetime

from campus_safety.iu_crime_log.classify import geocodable
from campus_safety.iu_crime_log.parse import CrimeLog
from campus_safety.lake.bronze import Manifest

SOURCE = "iu_crime_log"

OBSERVATIONS = (
    ("dataset", "VARCHAR"),  # bronze source: iu_crime_log, iu_crime_log_wayback
    ("source_ref", "VARCHAR"),  # bronze key of the snapshot
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),  # UTC, when we fetched it
    ("observed_at", "TIMESTAMP"),  # UTC, when the page showed this (archive capture or fetch)
    ("campus", "VARCHAR"),
    ("case_number", "VARCHAR"),
    ("offense", "VARCHAR"),
    ("offense_raw", "VARCHAR"),
    ("offense_count", "INTEGER"),
    ("date_reported", "DATE"),
    ("occurred_from", "TIMESTAMP"),  # local wall time, as the page gives it
    ("occurred_to", "TIMESTAMP"),
    ("location", "VARCHAR"),
    ("location_type", "VARCHAR"),
    ("geocodable", "BOOLEAN"),
    ("disposition", "VARCHAR"),
    ("severity", "VARCHAR"),
    ("sensitive", "BOOLEAN"),
)

RUNS = (
    ("dataset", "VARCHAR"),
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
    ("observed_at", "TIMESTAMP"),
    ("sha256", "VARCHAR"),
    ("http_status", "INTEGER"),
    ("parse_error", "VARCHAR"),  # null when the page parsed; redacted ParseError text otherwise
    ("window_start", "DATE"),  # the page's own date range, to learn its update cadence
    ("window_end", "DATE"),
    ("incidents", "INTEGER"),
    ("cases", "INTEGER"),
)


def _utc(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(tzinfo=None)


def observation_rows(log: CrimeLog, manifest: Manifest) -> list[tuple[object, ...]]:
    return [
        (
            manifest.source,
            manifest.key,
            manifest.run_id,
            _utc(manifest.fetched_at),
            _utc(manifest.observed_at),
            log.campus,
            incident.case_number,
            incident.offense,
            incident.offense_raw,
            incident.offense_count,
            incident.date_reported,
            incident.occurred_from,
            incident.occurred_to,
            incident.location,
            incident.location_type.value,
            geocodable(incident.location_type),
            incident.disposition,
            incident.severity.value,
            incident.sensitive,
        )
        for incident in log.incidents
    ]


def run_row(manifest: Manifest, log: CrimeLog | None, error: str | None) -> tuple[object, ...]:
    return (
        manifest.source,
        manifest.key,
        manifest.run_id,
        _utc(manifest.fetched_at),
        _utc(manifest.observed_at),
        manifest.sha256,
        manifest.http_status,
        error,
        log.window_start if log else None,
        log.window_end if log else None,
        len(log.incidents) if log else 0,
        len({i.case_number for i in log.incidents}) if log else 0,
    )
