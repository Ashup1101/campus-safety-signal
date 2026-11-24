"""Street names as one comparable key: "E 10TH ST", "10th Street" and "10TH" are all "10TH";
"N JORDAN AVE" is "JORDAN". Used for the city's layers and for IUPD location strings alike."""

import re
from dataclasses import dataclass

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


# Streets the city renamed; IUPD logs keep the old name (N Jordan Ave became N Eagleson Ave).
ALIASES = {"JORDAN": "EAGLESON"}
SIDES = {
    "N": "north",
    "NORTH": "north",
    "S": "south",
    "SOUTH": "south",
    "E": "east",
    "EAST": "east",
    "W": "west",
    "WEST": "west",
}
_SIDE_OF = re.compile(r"^\s*(NORTH|SOUTH|EAST|WEST|N|S|E|W)\s+OF\s+(.+?)\s*$")
_LETTER_O = re.compile(r"(?<=\d)O(?=TH\b|ST\b|ND\b|RD\b|\d)")
MIN_PREFIX = 4  # "JORDA" matches JORDAN; "JO" is too short to tell JONES from JORDAN


@dataclass(frozen=True)
class Segment:
    street: str  # street key, e.g. 10TH
    side: str  # north | south | east | west of the cross street
    cross: str  # street key of the cross street


def _resolve(name: str, known: set[str]) -> str | None:
    """A street key from IUPD text: typo-fixed, renamed, exact or a unique cut-off prefix."""
    key = street_key(_LETTER_O.sub("0", name.upper()))
    key = ALIASES.get(key, key)
    if key in known:
        return key
    # Old names count as prefixes too: a cut-off JORDA still finds EAGLESON.
    matches = {ALIASES.get(k, k) for k in known | set(ALIASES) if k.startswith(key)}
    if len(key) >= MIN_PREFIX and len(matches) == 1:
        found = matches.pop()
        return found if found in known else None
    return None


def parse_segment(text: str, known: set[str]) -> Segment | None:
    """'10TH STREET/EAST OF JORDA' -> Segment('10TH', 'east', 'EAGLESON'); anything unclear is
    None (left unplaced), never a guess."""
    street_part, slash, rest = text.upper().partition("/")
    side_of = _SIDE_OF.match(rest) if slash else None
    if not side_of:
        return None
    street, cross = _resolve(street_part, known), _resolve(side_of.group(2), known)
    if not street or not cross or street == cross:
        return None
    return Segment(street, SIDES[side_of.group(1)], cross)
