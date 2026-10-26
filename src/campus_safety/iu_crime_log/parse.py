"""Parse the IU daily crime log page.

The page has one table per campus, under an h2 naming the campus and an h3 date window. Each
incident is four rows: Case Number/Date Reported, Date Time From/To, Location/Crime
Description, Disposition. Any other shape raises ParseError, so a redesign fails loudly
instead of quietly parsing to nothing.

ParseError messages name row positions and field labels only, never cell contents: they reach
logs, including public CI logs, and a cell can hold a sensitive offense.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from html.parser import HTMLParser

from campus_safety.iu_crime_log.classify import (
    LocationType,
    Severity,
    is_sensitive,
    location_type,
    severity,
    split_offense,
)


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Incident:
    case_number: str
    offense: str  # count suffix stripped, so "X2" -> "X3" updates a row instead of adding one
    offense_count: int
    date_reported: date
    occurred_from: datetime | None  # local time; may be months before date_reported
    occurred_to: datetime | None
    location: str
    disposition: str

    @property
    def location_type(self) -> LocationType:
        return location_type(self.location)

    @property
    def severity(self) -> Severity:
        return severity(self.offense)

    @property
    def sensitive(self) -> bool:
        return is_sensitive(self.offense)


@dataclass(frozen=True)
class CrimeLog:
    campus: str
    window_start: date
    window_end: date
    incidents: tuple[Incident, ...]


_DASHES = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2212", "-"))
_WINDOW = re.compile(r"^(\d{2}/\d{2}/\d{4}) - (\d{2}/\d{2}/\d{4})$")
_LAYOUT = (
    ("Case Number", "Date Reported"),
    ("Date Time From", "Date Time To"),
    ("Location", "Crime Description"),
    ("Disposition", ""),
)
_NO_CRIMES = "There are no crimes to report"


def clean_text(text: str) -> str:
    """Collapse whitespace, unify dashes, and drop control and format characters.

    Format characters include zero-width and bidi-override code points, which can hide text
    from a reader but not from a model; this is untrusted input.
    """
    spaced = (" " if ch.isspace() else ch for ch in text)
    visible = "".join(ch for ch in spaced if unicodedata.category(ch) not in ("Cc", "Cf"))
    return " ".join(visible.translate(_DASHES).split())


@dataclass
class _Table:
    heading: str
    window: str
    rows: list[list[str]] = field(default_factory=list)
    closed: bool = False


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._heading = ""
        self._window = ""
        self._text: list[str] | None = None  # buffer for the open h2, h3, or td
        self._row: list[str] | None = None
        self._table: _Table | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h2", "h3", "td"):
            self._text = []
        elif tag == "tr":
            self._row = []
        elif tag == "table":
            self._table = _Table(self._heading, self._window)
            self.tables.append(self._table)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h2", "h3", "td") and self._text is not None:
            text = clean_text("".join(self._text))
            self._text = None
            if tag == "h2":
                self._heading, self._window = text, ""
            elif tag == "h3":
                self._window = text
            elif self._row is not None:
                self._row.append(text)
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self._table.closed = True
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def parse_crime_log(html: str, campus: str = "Bloomington") -> CrimeLog:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    heading = f"Daily Crime & Fire Log for the IU {campus} Campus"
    tables = [table for table in parser.tables if table.heading == heading]
    if len(tables) != 1:
        raise ParseError(f"expected one table headed {heading!r}, found {len(tables)}")
    table = tables[0]
    if not table.closed:
        raise ParseError(f"{campus} table is truncated")
    window = _WINDOW.match(table.window)
    if window is None:
        raise ParseError(f"{campus} date window is not MM/DD/YYYY - MM/DD/YYYY")
    return CrimeLog(
        campus=campus,
        window_start=_parse_time(window[1], "%m/%d/%Y", "window start").date(),
        window_end=_parse_time(window[2], "%m/%d/%Y", "window end").date(),
        incidents=_incidents(table.rows),
    )


def _incidents(rows: list[list[str]]) -> tuple[Incident, ...]:
    if len(rows) == 1 and len(rows[0]) == 1 and rows[0][0].startswith(_NO_CRIMES):
        return ()
    if not rows or len(rows) % len(_LAYOUT):
        raise ParseError(f"{len(rows)} table rows do not split into 4-row incidents")
    incidents: dict[tuple[str, str], Incident] = {}
    for first in range(0, len(rows), len(_LAYOUT)):
        group = rows[first : first + len(_LAYOUT)]
        for offset, (row, (left, right)) in enumerate(zip(group, _LAYOUT, strict=True)):
            if len(row) != 4 or row[0] != left or row[2] != right:
                raise ParseError(
                    f"table row {first + offset}: expected labels {left!r}/{right!r}"
                    f" in a 4-cell row, got {len(row)} cells"
                )
        incident = _incident(group, first)
        key = (incident.case_number, incident.offense)
        seen = incidents.get(key)
        if seen is None:
            incidents[key] = incident
        elif replace(seen, offense_count=incident.offense_count) == incident:
            # A repeated charge is sometimes listed as identical rows instead of an X2 suffix.
            total = seen.offense_count + incident.offense_count
            incidents[key] = replace(seen, offense_count=total)
        else:
            raise ParseError(
                f"table row {first}: repeats an earlier Case Number + Crime Description"
                " with different details"
            )
    return tuple(incidents.values())


def _incident(group: list[list[str]], first: int) -> Incident:
    ids, times, place, outcome = group
    case_number, description = ids[1], place[3]
    if not case_number or not description:
        raise ParseError(f"table row {first}: blank Case Number or Crime Description")
    offense, count = split_offense(description)
    return Incident(
        case_number=case_number,
        offense=offense,
        offense_count=count,
        date_reported=_parse_time(ids[3], "%m/%d/%Y", f"table row {first}: Date Reported").date(),
        occurred_from=_optional_time(times[1], f"table row {first + 1}: Date Time From"),
        occurred_to=_optional_time(times[3], f"table row {first + 1}: Date Time To"),
        location=place[1],
        disposition=outcome[1],
    )


def _optional_time(text: str, what: str) -> datetime | None:
    return _parse_time(text, "%m/%d/%Y %H:%M:%S", what) if text else None


def _parse_time(text: str, fmt: str, what: str) -> datetime:
    try:
        return datetime.strptime(text, fmt)
    except ValueError:
        raise ParseError(f"{what} does not match {fmt}") from None
