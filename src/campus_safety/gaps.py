"""The gap register (configs/gaps.yaml): where real public data is missing or too coarse.

Synthetic data (Phase 4) may patch only segments listed here, and every synthetic row carries the
gap_id it patches.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

REGISTER = Path(__file__).resolve().parents[2] / "configs" / "gaps.yaml"
SOURCES = {"iu_crime_log", "bpd_calls_for_service"}
_GAP_ID = re.compile(r"^[a-z0-9_]{3,64}$")


class GapRegisterError(ValueError):
    pass


@dataclass(frozen=True)
class Segment:
    source: str
    start: date | None  # None: the whole history of the source
    end: date | None
    fields: tuple[str, ...]


@dataclass(frozen=True)
class Gap:
    gap_id: str
    reason: str
    segment: Segment
    closing_source: str


def load(path: Path = REGISTER) -> list[Gap]:
    entries = (yaml.safe_load(path.read_text()) or {}).get("gaps", [])
    gaps = [_gap(entry) for entry in entries]
    ids = [gap.gap_id for gap in gaps]
    if len(ids) != len(set(ids)):
        raise GapRegisterError("duplicate gap_id")
    return gaps


def _gap(entry: dict[str, object]) -> Gap:
    gap_id, segment = entry.get("gap_id"), entry.get("segment")
    if not isinstance(gap_id, str) or not _GAP_ID.match(gap_id):
        raise GapRegisterError(f"bad gap_id: {gap_id!r}")
    if not isinstance(segment, dict):
        raise GapRegisterError(f"{gap_id}: segment must be a mapping")
    for key in ("reason", "closing_source"):
        if not isinstance(entry.get(key), str) or not str(entry[key]).strip():
            raise GapRegisterError(f"{gap_id}: {key} is required")
    source, start, end = segment.get("source"), segment.get("start"), segment.get("end")
    if source not in SOURCES:
        raise GapRegisterError(f"{gap_id}: unknown source {source!r}")
    for value in (start, end):
        if value is not None and not isinstance(value, date):
            raise GapRegisterError(f"{gap_id}: start and end must be YYYY-MM-DD or null")
    if isinstance(start, date) and isinstance(end, date) and start > end:
        raise GapRegisterError(f"{gap_id}: start is after end")
    fields = segment.get("fields")
    if not isinstance(fields, list) or not fields or not all(isinstance(f, str) for f in fields):
        raise GapRegisterError(f"{gap_id}: fields must be a non-empty list")
    return Gap(
        gap_id=gap_id,
        reason=str(entry["reason"]).strip(),
        segment=Segment(str(source), start, end, tuple(fields)),
        closing_source=str(entry["closing_source"]).strip(),
    )
