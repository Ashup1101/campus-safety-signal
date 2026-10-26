"""Labels derived from crime log text: offense count, severity tier, sensitivity, location type.

Rules are ordered regexes and the first match wins. An offense no rule matches comes back
UNCLASSIFIED, so new labels show up in the run log instead of landing in a tier by accident.
"""

import re
from enum import StrEnum


class Severity(StrEnum):
    HIGH = "high"  # violence, weapons, sexual violence
    MEDIUM = "medium"  # other offenses against people, property, impaired or reckless driving
    LOW = "low"  # alcohol, drugs, fraud, regulatory
    UNCLASSIFIED = "unclassified"


class LocationType(StrEnum):
    PLACE = "place"  # TETER QUAD, ATHLETIC/RED LOT
    ADDRESS = "address"  # 114 S INDIANA AVE
    BLOCK = "block"  # 500 BLK E KIRKWOOD
    STREET_SEGMENT = "street_segment"  # 3RD STREET/WEST OF EAGLESON
    CATCH_ALL = "catch_all"  # ALL OTHER CAMPUS BUILDINGS - BLOOMINGTON
    UNKNOWN = "unknown"  # blank


_COUNT_SUFFIX = re.compile(r"\s+X\s?(\d+)$")

_SEVERITY_RULES = tuple(
    (re.compile(pattern), severity)
    for pattern, severity in (
        (
            r"MURDER|HOMICIDE|MANSLAUGHTER|AGGRAVATED|ROBBERY|KIDNAP|CONFINEMENT|IMPRISONMENT"
            r"|STRANGULATION|RAPE|SODOMY|FONDLING|INCEST"
            r"|SEXUAL (ASSAULT|ASSUALT|BATTERY)"  # IU's log misspells ASSAULT
            r"|ARSON|\b(WEAPON|FIREARM|HANDGUN|GUN)S?\b|RIOT|BOMB|MODERATE INJURY|SERIOUS|DEATH",
            Severity.HIGH,
        ),
        # Ahead of MEDIUM, so "FALSE IDENTITY STATEMENT NO IDENTITY THEFT" is not read as theft.
        (r"FRAUD|FORGERY|COUNTERFEIT|IDENTITY|^FALSE", Severity.LOW),
        (
            r"BATTERY|ASSAULT|STALK|INTIMIDATION|HARASS|THREAT|BURGLARY|RESIDENTIAL ENTRY|THEFT"
            r"|SHOPLIFT|MISCHIEF|VANDAL|UNLAWFUL ENTRY|TRESPASS|RECKLESS|HAZING|INTOXICATED"
            r"|INJURY|DEALING|INTIMATE IMAGE|VOYEUR|INDECENT|EXPOSURE|CHILD|EXTORTION",
            Severity.MEDIUM,
        ),
        (
            r"ALCOHOL|INTOXICATION|LIQUOR|MARIJUANA|COCAINE|NARCOTIC|METHAMPHETAMINE|DRUG"
            r"|PARAPHERNALIA|SYRINGE|SCHEDULE|SUSPENDED|LICENSE|DISORDERLY|RESISTING|OBSTRUCTION"
            r"|PROPERTY DAMAGE CRASH|\bFIRE\b|NUDITY|DELINQUENCY|ALL OTHER CRIMINAL OFFENSES",
            Severity.LOW,
        ),
    )
)

# Kept out of every alert path: sexual offenses, and domestic, dating, stalking, and child
# cases, where even a time and place can identify the victim.
_SENSITIVE = re.compile(
    r"RAPE|\bSEX|SODOMY|FONDLING|INCEST|VOYEUR|INTIMATE IMAGE|NUDITY|INDECENT|EXPOSURE"
    r"|STALK|DOMESTIC|\bDATING VIOLENCE|STRANGULATION|INVASION OF PRIVACY|PROTECTIVE ORDER|CHILD"
)

_CATCH_ALL = re.compile(r"^ALL OTHER\b")
_SEGMENT = re.compile(r"\b(NORTH|SOUTH|EAST|WEST) OF\b")
_BLOCK = re.compile(r"^\d+ BLK\b")
_ADDRESS = re.compile(
    r"^\d+ ([NSEW]\.? |.*\b(ST|STREET|AVE|AVENUE|RD|ROAD|DR|DRIVE|LN|LANE|BLVD|PIKE|WAY|CT)\.?$)"
)


def split_offense(text: str) -> tuple[str, int]:
    """'ILLEGAL CONSUMPTION ... X5' -> ('ILLEGAL CONSUMPTION ...', 5): arrests or referrals."""
    match = _COUNT_SUFFIX.search(text)
    if match is None:
        return text, 1
    return text[: match.start()], int(match.group(1))


def severity(offense: str) -> Severity:
    for pattern, tier in _SEVERITY_RULES:
        if pattern.search(offense):
            return tier
    return Severity.UNCLASSIFIED


def is_sensitive(offense: str) -> bool:
    return _SENSITIVE.search(offense) is not None


def location_type(location: str) -> LocationType:
    if not location:
        return LocationType.UNKNOWN
    if _CATCH_ALL.match(location):
        return LocationType.CATCH_ALL
    if _SEGMENT.search(location):
        return LocationType.STREET_SEGMENT
    if _BLOCK.match(location):
        return LocationType.BLOCK
    if _ADDRESS.match(location):
        return LocationType.ADDRESS
    return LocationType.PLACE


def geocodable(kind: LocationType) -> bool:
    return kind not in (LocationType.CATCH_ALL, LocationType.UNKNOWN)
