"""Where an alert is: only the streets its official text names, never a guess.

A segment counts when the text writes its street as a street ("Kirkwood Avenue", "E 3rd St",
"Third Street"), so "Indiana University" never maps to Indiana Ave. When the text names a block
("400 block") that one of the street's segments has, the area narrows to that block.
"""

import re

SUFFIX = r"(?:avenue|ave|street|st|road|rd)\b"
ORDINALS = {"3rd": "third", "7th": "seventh", "10th": "tenth"}
BLOCK = re.compile(r"\b(\d{3,4})\s+block\b", re.IGNORECASE)


def street_core(name: str) -> str:
    """'E Kirkwood Ave, 400 block (...)' -> 'kirkwood'; 'N Dunn St, ...' -> 'dunn'."""
    street = name.split(",", 1)[0].lower().split()
    if street and street[0] in {"n", "s", "e", "w"}:
        street = street[1:]
    if street and re.fullmatch(SUFFIX, street[-1]):
        street = street[:-1]
    return " ".join(street)


def _names_street(text: str, core: str) -> bool:
    spellings = [core, *([ORDINALS[core]] if core in ORDINALS else [])]
    return any(
        re.search(rf"\b{re.escape(spelling)}\s+{SUFFIX}", text, re.IGNORECASE)
        for spelling in spellings
    )


def area_for(text: str, names: dict[str, str]) -> list[str]:
    """Segment ids (sorted) for the streets the text names, narrowed to a named block."""
    blocks = {f"{n} block" for n in BLOCK.findall(text)}
    by_street: dict[str, list[str]] = {}
    for segment_id, name in names.items():
        by_street.setdefault(street_core(name), []).append(segment_id)
    found: list[str] = []
    for core, ids in by_street.items():
        if not core or not _names_street(text, core):
            continue
        narrowed = [i for i in ids if any(b in names[i].lower() for b in blocks)]
        found.extend(narrowed or ids)
    return sorted(found)
