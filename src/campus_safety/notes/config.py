"""Community notes settings from configs/notes.yaml, validated at load."""

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "notes.yaml"


@dataclass(frozen=True)
class NotesConfig:
    threshold: int
    event_night_threshold: int
    text_limit: int
    nearby_m: int
    expiry_hours: int
    report_threshold: int
    tags: tuple[str, ...]
    safety_tags: tuple[str, ...]
    after_all_clear_tags: tuple[str, ...]
    alarming_words: tuple[str, ...]


def _positive(raw: dict[str, object], key: str, minimum: int = 1) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{key} must be a whole number of at least {minimum}")
    return value


def _words(raw: dict[str, object], key: str) -> tuple[str, ...]:
    value = raw.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f"{key} must be a list of words")
    return tuple(str(v).strip() for v in value)


def load(path: Path = CONFIG) -> NotesConfig:
    raw = yaml.safe_load(path.read_text()) or {}
    found = NotesConfig(
        threshold=_positive(raw, "threshold", 2),
        event_night_threshold=_positive(raw, "event_night_threshold", 2),
        text_limit=_positive(raw, "text_limit"),
        nearby_m=_positive(raw, "nearby_m"),
        expiry_hours=_positive(raw, "expiry_hours"),
        report_threshold=_positive(raw, "report_threshold"),
        tags=_words(raw, "tags"),
        safety_tags=_words(raw, "safety_tags"),
        after_all_clear_tags=_words(raw, "after_all_clear_tags"),
        alarming_words=tuple(w.lower() for w in _words(raw, "alarming_words")),
    )
    for key in ("safety_tags", "after_all_clear_tags"):
        if set(getattr(found, key)) - set(found.tags):
            raise ValueError(f"{key} must name tags from the tags list")
    if set(found.safety_tags) & set(found.after_all_clear_tags):
        raise ValueError("safety_tags and after_all_clear_tags must not overlap")
    return found
