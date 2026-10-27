"""Labels derived from crime log text: offense count, severity tier, sensitivity, location type.

Rules are ordered regexes and the first match wins. An offense no rule matches comes back
UNCLASSIFIED, so new labels show up in the run log instead of landing in a tier by accident.
"""

import re
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    HIGH = "high"  # violence, weapons, sexual violence
    MEDIUM = "medium"  # other offenses against people, property, impaired or reckless driving
    LOW = "low"  # alcohol, drugs, fraud, regulatory
    SERVICE = "service"  # non-criminal calls in the legacy CAD logs: assists, notices, accidents
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
        (r"FRAUD|FORGERY|COUNTERFEIT|IDENTITY|^FALSE|EMBEZZLEMENT", Severity.LOW),
        (
            r"BATTERY|ASSAULT|STALK|INTIMIDATION|HARASS|THREAT|BURGLARY|RESIDENTIAL ENTRY|THEFT"
            r"|SHOPLIFT|MISCHIEF|VANDAL|UNLAWFUL ENTRY|TRESPASS|RECKLESS|HAZING|INTOXICATED"
            r"|INJURY|DEALING|INTIMATE IMAGE|VOYEUR|INDECENT|EXPOSURE|CHILD|EXTORTION"
            # legacy (2011-2017) labels
            r"|FORCIBLE ENTRY|LARCENY|POCKET-PICKING|CONVERSION|DAMAGED PROPERTY|FROM BUILDING"
            r"|DATING VIOLENCE|DOMESTIC|UNDER THE INFLUENCE|PEEPING|\bSEX OFF|INVASION OF PRIVACY",
            Severity.MEDIUM,
        ),
        (
            r"ALCOHOL|INTOXICATION|LIQUOR|MARIJUANA|COCAINE|NARCOTIC|METHAMPHETAMINE|DRUG"
            r"|PARAPHERNALIA|SYRINGE|SCHEDULE|SUSPENDED|LICENSE|DISORDERLY|RESISTING|OBSTRUCTION"
            r"|PROPERTY DAMAGE CRASH|\bFIRE\b|NUDITY|DELINQUENCY|ALL OTHER CRIMINAL OFFENSES"
            # legacy (2011-2017) labels
            r"|CONSUMPTION|POSSESSION|STOLEN PROPERTY|BRIBERY|IMPERSONAT|TOXIC VAPORS|PROSTITUTION"
            r"|INDECENCY|SMOKING|SPEED CONTEST|STOP ARM|FINANCIAL RESPONSIBILITY|HIT & RUN"
            r"|DISTURBANCE|NOISE|LOUD PARTY|ALL OTHER OFFENSES|^ALL OTHER-|TRAFFIC VIOLATOR"
            r"|TRAFFIC CITATION",
            Severity.LOW,
        ),
        # Last, so "DUI // MEDICAL ASSIST" is a crime first and a service call never wins a tie.
        (
            r"(?i)ASSIST|WELFARE|LOST PROPERTY|SUSPICIOUS PERSON|WARRANT|SUMMONS|LEGAL NOTICE"
            r"|COURT SERVICE|MISSING PERSON|SUICIDE|NON-CRIMINAL|ADMINISTRATIVE|INVESTIGATING"
            r"|ACCIDENT|PROPERTY DAMAGE ONLY|VEHICLE STOP|SECURITY CHECK|^UNFOUNDED$",
            Severity.SERVICE,
        ),
    )
)

# Kept out of every alert path: sexual offenses, and domestic, dating, stalking, and child
# cases, where even a time and place can identify the victim; also suicide attempts and
# missing persons (health and welfare, not public threats).
_SENSITIVE = re.compile(
    r"RAPE|\bSEX|SODOMY|FONDLING|INCEST|VOYEUR|INTIMATE IMAGE|NUDITY|INDECENT|EXPOSURE"
    r"|STALK|DOMESTIC|\bDATING VIOLENCE|STRANGULATION|INVASION OF PRIVACY|PROTECTIVE ORDER|CHILD"
    r"|PEEPING|PROSTITUTION|INDECEN|SUICIDE|MISSING PERSON"
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


def record_unclassified(path: Path, labels: Iterable[str]) -> None:
    """Merge offense labels into a local, gitignored list. Labels can be sensitive, so they go
    here for review and never into a log."""
    known = set(path.read_text().splitlines()) if path.exists() else set()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{label}\n" for label in sorted(known | set(labels))))
