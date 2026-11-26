"""Shared registry for the small models trained off the laptop (T2 news relevance, T4 injection
screen, T3 crime-log fallback): lake models/<name>/<run_id>/ holds the scorecard, the model files
and a manifest of their SHA-256 hashes. Import is write-once. Only JSON (weights) and ONNX files
are accepted, never pickles, and every read checks the hash. The honesty switch is the scorecard's
"method": "model" only when the model beat the rules on its test set."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from campus_safety.lake.storage import Lake

ALLOWED = (".json", ".onnx")
METHODS = ("model", "rules")


@dataclass(frozen=True)
class Registered:
    name: str
    run_id: str
    card: dict[str, Any]
    hashes: dict[str, str]
    imported_at: str


def _prefix(name: str, run_id: str) -> str:
    return f"models/{name}/{run_id}/"


def _card(source: Path) -> dict[str, Any]:
    card = json.loads((source / "scorecard.json").read_text())
    if not isinstance(card.get("run_id"), str) or card.get("method") not in METHODS:
        raise ValueError("scorecard needs a run_id and a method of model or rules")
    return dict(card)


def import_run(lake: Lake, name: str, source: Path) -> str:
    """Copy one finished run into the lake. 'imported', or 'unchanged' when the same bytes are
    already there; different bytes under the same run id are refused."""
    card = _card(source)
    files = sorted(p for p in source.iterdir() if p.is_file() and p.name != "scorecard.json")
    if any(p.suffix not in ALLOWED for p in files):
        raise ValueError(f"model file type must be one of {ALLOWED}")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    hashes["scorecard.json"] = hashlib.sha256((source / "scorecard.json").read_bytes()).hexdigest()
    prefix = _prefix(name, str(card["run_id"]))
    if lake.keys(prefix):
        stored = json.loads(lake.get(prefix + "manifest.json"))
        if stored["hashes"] == hashes:
            return "unchanged"
        raise ValueError(f"run {card['run_id']} already imported with different files")
    for file in [*files, source / "scorecard.json"]:
        lake.create(prefix + file.name, file.read_bytes())
    manifest = {"hashes": hashes, "imported_at": datetime.now(UTC).isoformat()}
    lake.create(prefix + "manifest.json", json.dumps(manifest, sort_keys=True).encode())
    return "imported"


def runs(lake: Lake, name: str) -> list[Registered]:
    found = []
    for key in lake.keys(f"models/{name}/"):
        if key.endswith("/manifest.json"):
            prefix = key.removesuffix("manifest.json")
            manifest = json.loads(lake.get(key))
            card = json.loads(lake.get(prefix + "scorecard.json"))
            run_id = prefix.rstrip("/").rsplit("/", 1)[1]
            found.append(
                Registered(name, run_id, card, manifest["hashes"], manifest["imported_at"])
            )
    return sorted(found, key=lambda r: r.imported_at)


def latest(lake: Lake, name: str) -> Registered | None:
    found = runs(lake, name)
    return found[-1] if found else None


def read(lake: Lake, run: Registered, file: str) -> bytes:
    """A model file of an imported run, only if its bytes still match the manifest."""
    body = lake.get(_prefix(run.name, run.run_id) + file)
    if hashlib.sha256(body).hexdigest() != run.hashes.get(file):
        raise ValueError(f"{file}: hash does not match the imported manifest")
    return body


def uses_model(run: Registered) -> bool:
    return run.card.get("method") == "model"
