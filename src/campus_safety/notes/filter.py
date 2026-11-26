"""Server-side checks on community note text (optional, short). Blocked: links, emails, phone
numbers, money asks, descriptions of people, names, hidden characters, too long. Held for a
moderator: alarming words. Reasons are plain words for the poster; the text is never logged."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from campus_safety.notes.config import NotesConfig
from campus_safety.official.descriptors import strip_descriptors

Names = Callable[[str], list[str]]

_HIDDEN = re.compile("[​-‏‪-‮⁠-⁤﻿]")
_LINK = re.compile(
    r"https?://|www\.|\b[\w-]+\s*(?:\.|\[\.\]|\(\.\)|\s+dot\s+)\s*"
    r"(?:com|org|net|edu|gov|io|ly|gl|me|co|us|info|app|link|xyz|test)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+\s*(?:@|\[at\]|\(at\))\s*[\w-]+", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_MONEY = re.compile(
    r"venmo|cash\s?app|paypal|zelle|gofundme|donat|\$\s?\d|send\s+(?:me\s+)?money|\bpay\s+me\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Verdict:
    outcome: Literal["ok", "blocked", "held"]
    reason: str | None = None


def presidio_names() -> Names:
    """Person names via the project's Presidio setup (loaded on first use)."""
    from campus_safety.t3.privacy import PersonScreen

    screen = PersonScreen()
    return lambda text: screen.names(text)


def check(text: str, cfg: NotesConfig, names: Names) -> Verdict:
    if _HIDDEN.search(text):
        return Verdict("blocked", "hidden characters")
    clean = unicodedata.normalize("NFKC", text).strip()
    if len(clean) > cfg.text_limit:
        return Verdict("blocked", "too long")
    for pattern, reason in (
        (_EMAIL, "email"),  # before links: an address contains a domain
        (_LINK, "link"),
        (_PHONE, "phone number"),
        (_MONEY, "money"),
    ):
        if pattern.search(clean):
            return Verdict("blocked", reason)
    if strip_descriptors(clean) != clean:
        return Verdict("blocked", "description of a person")
    if names(clean):
        return Verdict("blocked", "name")
    lowered = clean.lower()
    if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in cfg.alarming_words):
        return Verdict("held", "needs review")
    return Verdict("ok")
