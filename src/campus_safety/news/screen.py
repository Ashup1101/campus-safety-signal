"""Screening before any model sees an item: relevance, cleaning, and injection defenses.

Every item is untrusted data (OWASP LLM01). Text is normalized and capped, instruction-like
phrases are flagged (the item is still processed, its answers count less and the flag is kept),
and model input is fenced with a per-run nonce so a page cannot forge the fence. Nothing an item
says ever changes what the pipeline does.
"""

import re
import secrets
import unicodedata
from dataclasses import dataclass

MAX_CHARS = 2_000

# Public-safety vocabulary. Broad on purpose: extraction decides the type, this only skips the
# city budget and basketball stories.
RELEVANT = re.compile(
    r"\b(shot|shoot|shooting|gunfire|gunshot|stabb|robber|assault|batter|burglar|break-?in|"
    r"theft|stole|stolen|vandal|arson|fire|crash|collision|hit-and-run|threat|weapon|gun|knife|"
    r"homicide|murder|killed|dead|injur|wound|hurt|victim|suspect|arrest|police|iupd|bpd|"
    r"sheriff|officer|emergency|evacuat|lockdown|shelter in place|missing|overdose|owi|dui|"
    r"intoxicat|explosion|bomb|hazmat|swat|crime|offense|incident|investigat|sexual|rape|"
    r"domestic|kidnap|abduct|carjack|standoff|pursuit|chase)\w*\b",
    re.IGNORECASE,
)

INJECTION = re.compile(
    r"ignore (?:all |the |any )?(?:previous|prior|above|earlier)|disregard\b.{0,40}instruction|"
    r"you are now\b|new instructions?\b|system prompt|\bas an ai\b|\bassistant:|\bsystem:|"
    r"<\s*/?\s*(?:system|instruction|prompt|tool)\b|\bBEGIN (?:SYSTEM|INSTRUCTION)|"
    r"\[INST\]|<\|im_start\|>|do not follow|respond (?:only )?with\b|output the (?:following|json)|"
    r"print (?:your|the) (?:prompt|instructions)|reveal\b.{0,20}(?:prompt|instructions)|"
    r"\bjailbreak\b|\bdan mode\b|developer mode|override\b.{0,20}(?:rules|safety)",
    re.IGNORECASE,
)

_DROP = {"Cc", "Cf", "Co", "Cn", "Cs"}  # control, format, private-use, unassigned, surrogates
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff]")


@dataclass(frozen=True)
class Screened:
    text: str  # cleaned, capped
    relevant: bool
    injection_suspected: bool


def clean(text: str, limit: int = MAX_CHARS) -> str:
    """NFKC, no control/format/zero-width characters, single spaces, capped."""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _DROP or ch in "\n\t")
    return " ".join(text.split())[:limit]


def screen(text: str) -> Screened:
    cleaned = clean(text)
    return Screened(
        cleaned,
        relevant=RELEVANT.search(cleaned) is not None,
        injection_suspected=INJECTION.search(cleaned) is not None,
    )


def nonce() -> str:
    return secrets.token_hex(8)


def fence(text: str, token: str) -> str:
    """The item as a fenced data block; a page cannot know the token, so it cannot close it."""
    return f"<<<ITEM {token}>>>\n{text}\n<<<END {token}>>>"
