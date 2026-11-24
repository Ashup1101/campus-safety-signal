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
    "PARKWAY",
    "BOULEVARD",
    "CIRCLE",
    "TRAIL",
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


# Streets the city renamed or names in full; IUPD logs keep the old or short name (N Jordan Ave
# became N Eagleson Ave; the bypass is "State Road 45 46 Bypass" in the city's layer).
ALIASES = {
    "JORDAN": "EAGLESON",
    "46 BYPASS": "STATE ROAD 45 46 BYPASS",
    "45 46 BYPASS": "STATE ROAD 45 46 BYPASS",
}
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
# "STREET/SIDE OF CROSS" or "STREET SIDE OF CROSS".
_STRETCH = re.compile(r"^\s*(.+?)\s*(?:/\s*|\s)(NORTH|SOUTH|EAST|WEST|N|S|E|W)\s+OF\s+(.+?)\s*$")
_LETTER_O = re.compile(r"(?<=\d)O(?=TH\b|ST\b|ND\b|RD\b|\d)")
MIN_PREFIX = 4  # "JORDA" matches JORDAN; "JO" is too short to tell JONES from JORDAN


@dataclass(frozen=True)
class Segment:
    street: str  # street key, e.g. 10TH
    side: str  # north | south | east | west of the cross street
    cross: str  # street key of the cross street


def _ordinal(number: str) -> str:
    n = int(number)
    suffix = "TH" if n % 100 in {11, 12, 13} else {1: "ST", 2: "ND", 3: "RD"}.get(n % 10, "TH")
    return f"{n}{suffix}"


def _key(name: str, known: set[str]) -> str:
    """Typo-fixed key; a cut-off street type ("1OTH STR") is dropped and a bare number is its
    ordinal ("10" can only be 10TH)."""
    key = street_key(_LETTER_O.sub("0", name.upper()))
    words = key.split()
    if key not in known and len(words) > 1 and any(s.startswith(words[-1]) for s in SUFFIXES):
        key = " ".join(words[:-1])
    return _ordinal(key) if key.isdigit() else key


def _resolve(name: str, known: set[str]) -> str | None:
    """A street key from IUPD text: typo-fixed, renamed, exact or a unique cut-off prefix."""
    key = _key(name, known)
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
    # The log merges repeated values with commas; the first one is the location.
    stretch = _STRETCH.match(text.upper().split(",")[0])
    if not stretch:
        return None
    street, cross = _resolve(stretch.group(1), known), _resolve(stretch.group(3), known)
    if not street or not cross or street == cross:
        return None
    return Segment(street, SIDES[stretch.group(2)], cross)


@dataclass(frozen=True)
class StreetAddress:
    number: int
    direction: str | None  # N | S | E | W when the text gives one
    street: str  # street key


_ADDRESS = re.compile(r"^\s*(\d+)\s+(?:(NORTH|SOUTH|EAST|WEST|N|S|E|W)\.?\s+)?(.+?)\s*$")


def parse_address(text: str, known: set[str]) -> StreetAddress | None:
    """'502 E. KIRKWOOD' -> StreetAddress(502, 'E', 'KIRKWOOD'). Only the first of comma-merged
    values counts, and a trailing ' - <Clery geography>' note is dropped."""
    found = _ADDRESS.match(text.upper().split(",")[0].split(" - ")[0])
    street = _resolve(found.group(3), known) if found else None
    if not found or not street:
        return None
    direction = found.group(2)[0] if found.group(2) else None
    return StreetAddress(int(found.group(1)), direction, street)
