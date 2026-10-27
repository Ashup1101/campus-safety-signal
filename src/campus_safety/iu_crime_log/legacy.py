"""Parse the pre-2018 IUPD daily crime log PDFs, as archived by the Wayback Machine.

Two layouts, one PDF per day:
- 2015-2017 "daily crime log report": a block per entry of "label: value" lines; case reports
  carry a report number, CAD events an event number and their own labels.
- 2011-2013 "Student Right To Know CAD Daily Log": text extraction yields each entry's labels
  first, then its values in a fixed order. An entry without a report number is a CAD event;
  its event number stands in as the case number.
Both map onto today's Incident. Anything else raises ParseError, naming positions only.
"""

import io
import re
from datetime import date, datetime

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from campus_safety.iu_crime_log.classify import split_offense
from campus_safety.iu_crime_log.parse import (
    CrimeLog,
    Incident,
    ParseError,
    clean_text,
    merge_repeats,
)

MAX_PAGES = 60
_STAMP = re.compile(r"(\d{2}/\d{2}/\d{2}) - [A-Z]{3} at (\d{2}:\d{2})", re.I)
_PAGE_HEADER = re.compile(
    r"^(Indiana University, Bloomington|Police Department|daily crime log report"
    r"|Student Right To Know CAD Daily Log|from \S.* to \S.*|Page \d+ of \d+"
    r"|\d+ Incidents Listed\.?|\d+ Page No\. .*)$",
    re.I,
)
_CAMPUS_SUFFIX = re.compile(r"\s+-\s+(On|Off|Non)[ -]?Campus$", re.I)

# 2015-2017 layout
_REPORT_WINDOW = re.compile(r"^from (\d{2}/\d{2}/\d{4}) \d{2}:\d{2} ?to (\d{2}/\d{2}/\d{4})", re.I)
_REPORTED = re.compile(r"^date reported: (.+?) (?:report|cad event) #: (\S+)$", re.I)
_FIELD = re.compile(
    r"^(general location|location|date occurred from|date occurred to|incident/offenses"
    r"|final incident|incident|disposition|modified date):\s*(.*)$",
    re.I,
)
_WRAPPABLE = (
    "general location",
    "location",
    "incident/offenses",
    "final incident",
    "incident",
    "disposition",
)

# 2011-2013 layout
_CAD_WINDOW = re.compile(r"^From (\w{3} \d{2}, \d{4}) to (\w{3} \d{2}, \d{4})", re.I)
_CAD_LABELS = {
    "Date Reported:",
    "Incident :",
    "Disposition:",
    "Event #:",
    "Report #:",
    "Location :",
}
_CAD_OCCURRED = "Date and Time Occurred From - Occurred To"
_CAD_PLACE = re.compile(r"^(.*?)\s*(\d{2}-\d{2}-\d{2}-\d{6})(?:\s*Location :)?$")


def extract_text(body: bytes) -> str:
    if b"%PDF" not in body[:1024]:
        raise ParseError("not a PDF; the archive may have stored an error page")
    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if len(reader.pages) > MAX_PAGES:
            raise ParseError(f"PDF has more than {MAX_PAGES} pages")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPdfError as e:
        raise ParseError(f"unreadable PDF ({type(e).__name__})") from None


def parse_legacy_pdf(body: bytes) -> CrimeLog:
    return parse_legacy_text(extract_text(body))


def parse_legacy_text(text: str) -> CrimeLog:
    lines = [line for line in (clean_text(raw) for raw in text.splitlines()) if line]
    head = " ".join(lines[:8]).lower()
    if "student right to know" in head:
        return _parse_cad(lines)
    if "daily crime log report" in head:
        return _parse_report(lines)
    raise ParseError("unknown legacy layout")


def _window(lines: list[str], pattern: re.Pattern[str], fmt: str) -> tuple[date, date]:
    for line in lines[:10]:
        match = pattern.match(line)
        if match:
            try:
                return (
                    datetime.strptime(match[1], fmt).date(),
                    datetime.strptime(match[2], fmt).date(),
                )
            except ValueError:
                break
    raise ParseError("legacy date window missing or malformed")


def _stamp(text: str, what: str) -> datetime | None:
    if not text:
        return None
    match = _STAMP.search(text)
    if match is None:
        raise ParseError(f"{what} is not MM/DD/YY - DAY at HH:MM")
    at = datetime.strptime(f"{match[1]} {match[2]}", "%m/%d/%y %H:%M")
    return None if at == datetime(2000, 1, 1) else at  # 01/01/00 00:00 means unknown


def _incident(
    where: str,
    case: str,
    reported: datetime | None,
    offense: str,
    location: str,
    disposition: str,
    occurred: tuple[datetime | None, datetime | None],
) -> tuple[str, Incident]:
    if not case or not offense or reported is None:
        raise ParseError(f"{where}: blank case number, offense, or date reported")
    label, count = split_offense(offense)
    return where, Incident(
        case_number=case,
        offense=label,
        offense_raw=offense,
        offense_count=count,
        date_reported=reported.date(),
        occurred_from=occurred[0],
        occurred_to=occurred[1],
        location=_CAMPUS_SUFFIX.sub("", location),
        disposition=disposition.rstrip(". "),
    )


def _parse_report(lines: list[str]) -> CrimeLog:
    start, end = _window(lines, _REPORT_WINDOW, "%m/%d/%Y")
    blocks: list[dict[str, str]] = []
    field: str | None = None
    for number, line in enumerate(lines):
        if _PAGE_HEADER.match(line):
            continue
        reported = _REPORTED.match(line)
        if reported:
            blocks.append({"date reported": reported[1], "report #": reported[2]})
            field = None
            continue
        match = _FIELD.match(line)
        if match and blocks:
            field = match[1].lower()
            blocks[-1][field] = match[2]
        elif blocks and field in _WRAPPABLE:
            blocks[-1][field] += f" {line}"  # a value wrapped onto the next line
        else:
            raise ParseError(f"line {number}: not a label or a wrapped value")
    found = []
    for position, block in enumerate(blocks):
        where = f"entry {position}"
        occurred = (
            _stamp(block.get("date occurred from", ""), f"{where} occurred from"),
            _stamp(block.get("date occurred to", ""), f"{where} occurred to"),
        )
        found.append(
            _incident(
                where,
                block["report #"],
                _stamp(block["date reported"], f"{where} date reported"),
                # CAD events: the final incident type wins over the initial call type.
                block.get("incident/offenses")
                or block.get("final incident")
                or block.get("incident", ""),
                block.get("general location") or block.get("location", ""),
                block.get("disposition", ""),
                occurred,
            )
        )
    return CrimeLog("Bloomington", start, end, merge_repeats(found))


def _parse_cad(lines: list[str]) -> CrimeLog:
    start, end = _window(lines, _CAD_WINDOW, "%b %d, %Y")
    entries: list[list[str]] = []
    for line in lines:
        if line == "Date Reported:":
            entries.append([])
        elif entries and line not in _CAD_LABELS and not _PAGE_HEADER.match(line):
            entries[-1].append(line)
    found = []
    for position, entry in enumerate(entries):
        where = f"entry {position}"
        occurred = [line for line in entry if line.startswith(_CAD_OCCURRED)]
        values = [line for line in entry if not line.startswith(_CAD_OCCURRED)]
        if len(occurred) != 1 or len(values) not in (4, 5):
            raise ParseError(f"{where}: expected 4 or 5 values and one occurred line")
        place = _CAD_PLACE.match(values[3])
        if place is None:
            raise ParseError(f"{where}: location line has no CAD event number")
        report = values[4] if len(values) == 5 else ""
        if report and not report.isdigit():
            raise ParseError(f"{where}: report number is not numeric")
        times = _STAMP.findall(occurred[0])
        if len(times) not in (0, 2):
            raise ParseError(f"{where}: occurred line needs both ends or neither")
        ends = [_stamp(f"{day} - XXX at {hour}", f"{where} occurred") for day, hour in times]
        found.append(
            _incident(
                where,
                report or place[2],
                _stamp(values[0], f"{where} date reported"),
                values[1],
                place[1],
                values[2],
                (ends[0], ends[1]) if ends else (None, None),
            )
        )
    return CrimeLog("Bloomington", start, end, merge_repeats(found))
