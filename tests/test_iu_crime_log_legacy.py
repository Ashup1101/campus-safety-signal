from datetime import date, datetime

import pytest
from legacy_pdf import CAD, REPORT, make_pdf

from campus_safety.iu_crime_log.legacy import extract_text, parse_legacy_pdf, parse_legacy_text
from campus_safety.iu_crime_log.parse import ParseError


def test_report_layout_with_case_reports_and_cad_events() -> None:
    log = parse_legacy_text("\n".join(REPORT))
    assert (log.window_start, log.window_end) == (date(2016, 2, 16), date(2016, 2, 16))
    report, event = log.incidents
    assert report.case_number == "900445"
    assert report.offense == "VANDALISM, MISCHIEF"
    assert report.location == "SAMPLE HALL"
    assert report.date_reported == date(2016, 2, 16)
    assert report.occurred_from == datetime(2016, 2, 12, 17, 0)
    assert report.occurred_to == datetime(2016, 2, 16, 13, 0)
    assert event.case_number == "16-02-16-000123"
    assert event.offense == "THEFT FROM BUILDING"  # final incident, wrapped onto two lines
    assert event.location == "SAMPLE LOT"
    assert event.occurred_from is None


def test_cad_layout_with_and_without_report_numbers() -> None:
    log = parse_legacy_text("\n".join(CAD))
    assert (log.window_start, log.window_end) == (date(2013, 2, 4), date(2013, 2, 4))
    rape, drunk = log.incidents
    assert rape.case_number == "900403"
    assert rape.sensitive
    assert rape.disposition == "ACTIVE"
    assert rape.location == "400 BLK N SAMPLE"
    assert rape.occurred_from == datetime(2013, 2, 3, 0, 0)
    assert drunk.case_number == "13-02-04-000041"  # CAD event: no report number
    assert drunk.location == "SAMPLE MEMORIAL UNION"  # wrapped onto a second line
    assert drunk.disposition == "FAILED TO LOCATE"
    assert (drunk.occurred_from, drunk.occurred_to) == (None, None)


@pytest.mark.parametrize(
    "title",
    ["Daily Crime Log", "Daily Crime Report", "Daily Crime Report Log", "DAILY CRIME LOG REPORT"],
)
def test_report_titles_over_the_years(title: str) -> None:
    lines = [REPORT[0], REPORT[1], title, *REPORT[3:]]
    assert len(parse_legacy_text("\n".join(lines)).incidents) == 2


def test_arrest_logs_are_not_parsed() -> None:
    with pytest.raises(ParseError, match="unknown legacy layout"):
        parse_legacy_text("Adult Arrest Log\nAgency :\nAdult Arrest Log UCR Identifier :")


def test_pdf_round_trip() -> None:
    log = parse_legacy_pdf(make_pdf(REPORT))
    assert [i.case_number for i in log.incidents] == ["900445", "16-02-16-000123"]


def test_archived_error_page_is_not_a_pdf() -> None:
    with pytest.raises(ParseError, match="not a PDF"):
        extract_text(b"<!DOCTYPE html><html>Wayback error</html>")


def test_corrupt_pdf_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="unreadable PDF"):
        extract_text(b"%PDF-1.4\n" + b"\x00garbage" * 20)


MARK = "ZQXJ"


@pytest.mark.parametrize(
    "lines",
    [
        ["Some Other Report", f"{MARK} 1"],
        [*REPORT[:4], f"stray {MARK} line", *REPORT[4:]],
        [*REPORT[:4], f"date reported: {MARK} report #: 1", f"incident/offenses: {MARK}"],
        [*CAD[:6], f"Stray {MARK} after the occurred row", *CAD[6:]],
        [*CAD[:4], *CAD[5:]],
        [*CAD[:6], f"Incident : {MARK} Report #: {MARK}9", *CAD[7:]],
        [CAD[0], f"From {MARK} to {MARK}", *CAD[2:]],
    ],
    ids=[
        "unknown layout",
        "stray line",
        "bad date",
        "stray CAD line",
        "row before Date Reported",
        "non-numeric report",
        "bad window",
    ],
)
def test_legacy_errors_name_positions_not_contents(lines: list[str]) -> None:
    with pytest.raises(ParseError) as error:
        parse_legacy_text("\n".join(lines))
    assert MARK not in str(error.value)


def test_legacy_sources_are_each_entrys_lines() -> None:
    report, event = parse_legacy_text("\n".join(REPORT)).sources
    assert report.splitlines()[0].startswith("date reported:") and "report #: 900445" in report
    assert "modified date:" in report and "cad event #" not in report
    assert event.splitlines()[-1] == "disposition: REPORT FILED"
    rape, drunk = parse_legacy_text("\n".join(CAD)).sources
    assert rape.splitlines()[0].startswith("Date Reported:") and len(rape.splitlines()) == 4
    assert "UNION" in drunk and "Incidents Listed" not in drunk
