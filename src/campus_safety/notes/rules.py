"""Community note rules: what may be posted when (live alert, all-clear) and what shows
(corroboration). Pure functions over plain dicts so the server and tests share them."""

from collections.abc import Sequence
from typing import Any

from campus_safety.notes.config import NotesConfig

COUNTED = ("pending", "visible")  # held (review) and hidden (reports, moderator) never count


def corroborated(
    notes: Sequence[dict[str, Any]], *, event_night: bool, cfg: NotesConfig
) -> list[dict[str, Any]]:
    """Tags at least `threshold` different people posted (more on event nights), with the text of
    only those people. Order: most people first, then tag."""
    need = cfg.event_night_threshold if event_night else cfg.threshold
    by_tag: dict[str, list[dict[str, Any]]] = {}
    for n in notes:
        if n["state"] in COUNTED:
            by_tag.setdefault(str(n["tag"]), []).append(n)
    shown = []
    for tag, posted in by_tag.items():
        people = {n["account_id"] for n in posted}
        if len(people) >= need:
            texts = [str(n["text"]) for n in posted if n.get("text")]
            shown.append({"tag": tag, "people": len(people), "texts": texts})
    return sorted(shown, key=lambda s: (-s["people"], s["tag"]))
