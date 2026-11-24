"""Street names as one comparable key: "E 10TH ST", "10th Street" and "10TH" are all "10TH";
"N JORDAN AVE" is "JORDAN". Used for the city's layers and for IUPD location strings alike."""

import re

DIRECTIONS = {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST"}
SUFFIXES = {
    "ST",
    "STREET",
    "AVE",
    "AVENUE",
    "AV",
    "RD",
    "ROAD",
    "LN",
    "LANE",
    "DR",
    "DRIVE",
    "BLVD",
    "PL",
    "PLACE",
    "CT",
    "COURT",
    "WAY",
    "PKWY",
    "PIKE",
    "CIR",
    "TRL",
    "HWY",
    "SQ",
}
_WORD = re.compile(r"[A-Z0-9]+")


def street_key(name: str) -> str:
    """Upper-case words without a leading direction or trailing street type."""
    words = _WORD.findall(name.upper().replace("'", ""))
    if len(words) > 1 and words[0] in DIRECTIONS:
        words = words[1:]
    while len(words) > 1 and words[-1] in SUFFIXES:
        words = words[:-1]
    return " ".join(words)
