"""LLM fallback for crime log snapshots the rules parser could not read.

Only legacy PDFs with readable text that look like incident logs are eligible: arrest and media
logs (they name people), archive error pages, and empty page templates never are. An eligible PDF
is split into entries at "date reported" and each entry goes to the local model. Answers are
validated and cached under the cache dir by snapshot sha256 and model digest; `make transform
EXTRACTOR=llm_fallback` reads only that cache, so the transform itself never calls a model.
Recovered rows are tagged llm_fallback until the owner verifies them.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from campus_safety.iu_crime_log import backfill, silver
from campus_safety.iu_crime_log.legacy import extract_text, parse_legacy_pdf
from campus_safety.iu_crime_log.parse import Incident, ParseError, clean_text, parse_crime_log
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake
from campus_safety.t3.schema import FIELDS, messages
from campus_safety.t3.score import parse_output

_EXCLUDED = re.compile(r"arrest log|media log", re.I)
_ENTRY_START = re.compile(r"^date reported", re.I)

Chat = Callable[[str, list[dict[str, str]]], str]


@dataclass
class FallbackSummary:
    failed_snapshots: int = 0
    ineligible: int = 0
    eligible: int = 0
    cached: int = 0
    entries: int = 0
    recovered: int = 0
    invalid: int = 0


def entries(manifest: bronze.Manifest, body: bytes) -> list[str] | None:
    """The entry texts of an eligible snapshot, or None when it must not go to a model."""
    if not manifest.key.endswith(".pdf.gz"):
        return None  # HTML failures are empty archive templates
    try:
        lines = [
            line for line in (clean_text(raw) for raw in extract_text(body).splitlines()) if line
        ]
    except ParseError:
        return None  # error pages saved as PDFs, unreadable files
    if _EXCLUDED.search(" ".join(lines[:8])):
        return None
    found: list[list[str]] = []
    for line in lines:
        if _ENTRY_START.match(line):
            found.append([line])
        elif found:
            found[-1].append(line)
    return ["\n".join(entry) for entry in found] or None


def _stamp(value: object, fmt: str) -> bool:
    try:
        datetime.strptime(str(value), fmt)
    except ValueError:
        return False
    return True


def valid(fields: dict[str, object]) -> bool:
    """A model answer usable as an observation: every key, the required ones filled, formats."""
    if set(fields) != set(FIELDS):
        return False
    if not all(
        isinstance(fields[k], str) and str(fields[k]).strip() for k in ("case_number", "offense")
    ):
        return False
    if not _stamp(fields["date_reported"], "%Y-%m-%d"):
        return False
    for key in ("occurred_from", "occurred_to"):
        if fields[key] is not None and not _stamp(fields[key], "%Y-%m-%dT%H:%M"):
            return False
    count = fields["offense_count"]
    return isinstance(count, int) and not isinstance(count, bool) and count >= 1


def _rules_parse(manifest: bronze.Manifest, body: bytes) -> None:
    if manifest.key.endswith(".pdf.gz"):
        parse_legacy_pdf(body)
    else:
        parse_crime_log(body.decode("utf-8", errors="replace"))


def run(lake: Lake, model: str, digest: str, cache_dir: Path, chat: Chat) -> FallbackSummary:
    summary = FallbackSummary()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for dataset in (silver.SOURCE, backfill.SOURCE):
        for manifest in bronze.manifests(lake, dataset):
            body = bronze.read(lake, manifest)
            try:
                _rules_parse(manifest, body)
                continue
            except ParseError:
                summary.failed_snapshots += 1
            texts = entries(manifest, body)
            if texts is None:
                summary.ineligible += 1
                continue
            summary.eligible += 1
            path = cache_dir / f"{manifest.sha256[:16]}_{digest}.json"
            if path.exists():
                summary.cached += 1
                continue
            rows = []
            for index, text in enumerate(texts):
                answer = chat(model, messages(text))
                fields = parse_output(answer)
                ok = fields is not None and valid(fields)
                summary.entries += 1
                summary.recovered += ok
                summary.invalid += not ok
                rows.append(
                    {
                        "entry": index,
                        "source": text,
                        "answer": answer,
                        "fields": fields if ok else None,
                    }
                )
            record = {
                "snapshot": manifest.key,
                "sha256": manifest.sha256,
                "model": model,
                "digest": digest,
                "rows": rows,
            }
            path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
    return summary


def cached_incidents(cache_dir: Path, sha256: str) -> list[Incident]:
    """Incidents recovered for one snapshot (newest cache file wins), or [] if none."""
    files = sorted(cache_dir.glob(f"{sha256[:16]}_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return []
    found = []
    for row in json.loads(files[-1].read_text())["rows"]:
        fields = row.get("fields")
        if not fields:
            continue
        found.append(
            Incident(
                case_number=str(fields["case_number"]),
                offense=str(fields["offense"]),
                offense_raw=str(fields["offense"]),
                offense_count=int(fields["offense_count"]),
                date_reported=date.fromisoformat(str(fields["date_reported"])),
                occurred_from=_time(fields["occurred_from"]),
                occurred_to=_time(fields["occurred_to"]),
                location=str(fields["location"] or ""),
                disposition=str(fields["disposition"] or ""),
            )
        )
    return found


def _time(value: object) -> datetime | None:
    return None if value is None else datetime.strptime(str(value), "%Y-%m-%dT%H:%M")
