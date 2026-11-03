"""Remove suspect descriptions from official alert text before it is stored.

Live alerts are relayed exactly as sent. Anything kept afterwards (history views, silver/gold,
training data) gets this version: a sentence that describes a person (race, build, height, age,
clothing) is replaced by a marker. Vehicle descriptions and directions stay.
"""

import re

MARKER = "[description removed]"

_RACE = (
    r"white|black|hispanic|latino|latina|latinx|asian|caucasian|african[- ]american|biracial|"
    r"multiracial|native american|middle[- ]eastern|arab"
)
_PERSON = r"males?|females?|man|men|woman|women|juveniles?|teens?|boys?|girls?|person|people"
_DESCRIPTOR = re.compile(
    rf"described as|description|\bwearing\b|\b\d\s*'\s*\d{{1,2}}\b|\b\d\s*(?:ft|feet)\b|"
    rf"\b(?:{_RACE})\b(?:\W+\w+){{0,3}}?\W+(?:{_PERSON})\b|"
    rf"\b(?:{_PERSON})\b(?:\W+\w+){{0,2}}?\W+(?:{_RACE})\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def strip_descriptors(text: str) -> str:
    kept: list[str] = []
    for sentence in _SENTENCE.split(text.strip()):
        if not _DESCRIPTOR.search(sentence):
            kept.append(sentence)
        elif not kept or kept[-1] != MARKER:
            kept.append(MARKER)
    return " ".join(kept)
