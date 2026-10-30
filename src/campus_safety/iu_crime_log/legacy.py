"""Parse the pre-2018 IUPD daily crime log PDFs, as archived by the Wayback Machine.

Two layouts, one PDF per day:
- 2015-2017 "daily crime log report": a block per entry of "label: value" lines; case reports
  carry a report number, CAD events an event number and their own labels.
- 2011-2013 "Student Right To Know CAD Daily Log": a four-row form per entry, read in pypdf's
  layout mode so each label stays on the row with its value (plain extraction scrambles them).
  An entry without a report number is a CAD event; its event number stands in as the case number.
Both map onto today's Incident. Anything else raises ParseError, naming positions only.
"""

import re
from datetime import date, datetime

from campus_safety import pdf
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
    r"^(Indiana University, Bloomington|Police Department|daily crime (report( log)?|log( report)?)"
    r"|Student Right To Know CAD Daily Log|from \S.* to \S.*|Page \d+ of \d+"
    r"|\d+ Incidents Listed\.?|\d+ Page No\. .*)$",
    re.I,
)
_CAMPUS_SUFFIX = re.compile(
    r"\s+-\s+((On|Off|Non)[ -]?Campus|Non[ -]?campus property|Public property)$", re.I
)

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

# 2011-2013 layout, as rows in layout-mode text
_CAD_WINDOW = re.compile(
    r"^From (\w{3} \d{2}, \d{4})(?: \d{2}:\d{2})? to (\w{3} \d{2}, \d{4})", re.I
)
# Label case and the occurred row's colon vary between years.
_CAD_ROWS = {
    "reported": re.compile(
        r"^Date Reported:\s*(.*?)\s*Location ?:\s*(.*?)\s*Event #:\s*(\S*)$", re.I
    ),
    "occurred": re.compile(r"^Date and Time Occurred From - Occurred To:?\s*(.*)$", re.I),
    "incident": re.compile(r"^Incident ?:\s*(.*?)\s*Report #:\s*(\S*)$", re.I),
    "disposition": re.compile(r"^Disposition:\s*(.*)$", re.I),
}
_CAD_FOOTER = re.compile(r"^(\d+|Print Date and Time at|\d+ Page No\..*|Page No\..*)$", re.I)


def extract_text(body: bytes, layout: bool = False) -> str:
    return pdf.extract_text(body, MAX_PAGES, layout=layout)


def parse_legacy_pdf(body: bytes) -> CrimeLog:
    text = extract_text(body)
    if "student right to know" in text[:400].lower():
        return parse_legacy_text(extract_text(body, layout=True))
    return parse_legacy_text(text)


def parse_legacy_text(text: str) -> CrimeLog:
    lines = [line for line in (clean_text(raw) for raw in text.splitlines()) if line]
    head = " ".join(lines[:8]).lower()
    if "student right to know" in head:
        return _parse_cad(lines)
    # Titled "Daily Crime Log", "Daily Crime Log Report", "Daily Crime Report (Log)" over the years.
    # Arrest and media logs (which name people) are different documents and stay unparsed.
    if re.search(r"daily crime (report|log)", head):
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
    source: list[str],
    case: str,
    reported: datetime | None,
    offense: str,
    location: str,
    disposition: str,
    occurred: tuple[datetime | None, datetime | None],
) -> tuple[str, Incident, str]:
    if not case or not offense or reported is None:
        raise ParseError(f"{where}: blank case number, offense, or date reported")
    label, count = split_offense(offense)
    return (
        where,
        Incident(
            case_number=case,
            offense=label,
            offense_raw=offense,
            offense_count=count,
            date_reported=reported.date(),
            occurred_from=occurred[0],
            occurred_to=occurred[1],
            location=_CAMPUS_SUFFIX.sub("", location),
            disposition=disposition.rstrip(". "),
        ),
        "\n".join(source),
    )


def _parse_report(lines: list[str]) -> CrimeLog:
    start, end = _window(lines, _REPORT_WINDOW, "%m/%d/%Y")
    blocks: list[dict[str, str]] = []
    block_lines: list[list[str]] = []
    field: str | None = None
    for number, line in enumerate(lines):
        if _PAGE_HEADER.match(line):
            continue
        reported = _REPORTED.match(line)
        if reported:
            blocks.append({"date reported": reported[1], "report #": reported[2]})
            block_lines.append([line])
            field = None
            continue
        if block_lines:
            block_lines[-1].append(line)
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
                block_lines[position],
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
    return CrimeLog("Bloomington", start, end, *merge_repeats(found))


def _parse_cad(lines: list[str]) -> CrimeLog:
    start, end = _window(lines, _CAD_WINDOW, "%b %d, %Y")
    entries: list[dict[str, list[str]]] = []
    entry_lines: list[list[str]] = []
    last: str | None = None
    for number, line in enumerate(lines):
        if _PAGE_HEADER.match(line) or _CAD_FOOTER.match(line):
            continue
        if entry_lines and not line.lower().startswith("date reported:"):
            entry_lines[-1].append(line)
        row = next(
            ((name, m) for name, m in ((n, p.match(line)) for n, p in _CAD_ROWS.items()) if m), None
        )
        if row is not None:
            name, match = row
            if name == "reported":
                entries.append({})
                entry_lines.append([line])
            if not entries:
                raise ParseError(f"line {number}: row before the first Date Reported")
            entries[-1][name] = list(match.groups())
            last = name
        elif entries and last in ("reported", "incident", "disposition"):
            # A wrapped value: location continues the Date Reported row; the others their own row.
            field = entries[-1][last]
            index = 1 if last == "reported" else 0
            field[index] = f"{field[index]} {line}".strip()
        else:
            raise ParseError(f"line {number}: not a row label or a wrapped value")
    found = []
    for position, entry in enumerate(entries):
        where = f"entry {position}"
        if set(entry) != set(_CAD_ROWS):
            raise ParseError(f"{where}: missing one of the four rows")
        reported, location, event = entry["reported"]
        incident, report = entry["incident"]
        if report and not report.isdigit():
            raise ParseError(f"{where}: report number is not numeric")
        times = _STAMP.findall(entry["occurred"][0])
        if len(times) not in (0, 2):
            raise ParseError(f"{where}: occurred row needs both ends or neither")
        ends = [_stamp(f"{day} - XXX at {hour}", f"{where} occurred") for day, hour in times]
        found.append(
            _incident(
                where,
                entry_lines[position],
                report or event,
                _stamp(reported, f"{where} date reported"),
                incident,
                location,
                entry["disposition"][0],
                (ends[0], ends[1]) if ends else (None, None),
            )
        )
    return CrimeLog("Bloomington", start, end, *merge_repeats(found))
