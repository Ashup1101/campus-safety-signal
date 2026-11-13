"""Plain-word incident categories for reasons and levels (shared by the demo and gold tables).

Sensitive offenses never reach these functions: callers filter is_sensitive first.
"""

import re

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("shooting", r"SHOOTING|SHOTS FIRED|DISCHARG"),
    ("robbery", r"ROBBERY"),
    ("weapons incident", r"WEAPON|FIREARM|HANDGUN|\bGUN\b"),
    ("assault", r"ASSAULT|BATTERY"),
    ("burglary", r"BURGLARY|UNLAWFUL ENTRY"),
    ("traffic incident", r"DRIVING|CRASH|HIT & RUN|OPERATING|LICENSE"),
    ("theft", r"THEFT|LARCENY|SHOPLIFT"),
    ("vandalism report", r"VANDAL|MISCHIEF|GRAFFITI"),
    ("alcohol incident", r"ALCOHOL|LIQUOR|INTOXICAT|DRUNK|CONSUMPTION"),
    ("drug incident", r"DRUG|NARCOTIC|MARIJUANA|PARAPHERNALIA|METHAMPHETAMINE|COCAINE"),
    ("harassment report", r"HARASSMENT|INTIMIDATION"),
    ("disorderly conduct report", r"DISORDERLY|DISTURB"),
    ("trespass report", r"TRESPASS"),
    ("fake ID case", r"FALSE .*IDENTIFICATION|FAKE ID"),
    ("police obstruction report", r"RESISTING|OBSTRUCTION"),
)
SERIOUS = frozenset({"shooting", "robbery", "weapons incident"})
_COMPILED = tuple((name, re.compile(rx)) for name, rx in CATEGORIES)


def category(incident_type: str) -> str:
    text = incident_type.upper()
    return next((name for name, rx in _COMPILED if rx.search(text)), "other incident")


def is_serious(incident_type: str, severity_tier: str | None) -> bool:
    return severity_tier == "high" or category(incident_type) in SERIOUS


def plural(noun: str, n: int) -> str:
    if n == 1:
        return noun
    return noun[:-1] + "ies" if noun.endswith("y") and noun[-2] not in "aeiou" else noun + "s"
