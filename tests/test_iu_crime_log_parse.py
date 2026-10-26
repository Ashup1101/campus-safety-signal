from datetime import date, datetime

import pytest
from crime_log_html import NO_CRIMES, incident, page, section

from campus_safety.iu_crime_log.parse import ParseError, clean_text, parse_crime_log


def test_parses_bloomington_table_only() -> None:
    html = page(
        section("Bloomington", incident(case="900001")),
        section("Indianapolis", incident(case="900002")),
    )
    log = parse_crime_log(html)
    assert log.campus == "Bloomington"
    assert [i.case_number for i in log.incidents] == ["900001"]


def test_reads_window_bounds() -> None:
    html = page(section("Bloomington", incident(), window="08/19/2026 - 10/18/2026"))
    log = parse_crime_log(html)
    assert (log.window_start, log.window_end) == (date(2026, 8, 19), date(2026, 10, 18))


def test_reads_every_field() -> None:
    (only,) = parse_crime_log(page(section("Bloomington", incident()))).incidents
    assert only.case_number == "900001"
    assert only.offense == "THEFT FROM BUILDING LESS THAN $750"
    assert only.offense_count == 1
    assert only.date_reported == date(2026, 10, 25)
    assert only.occurred_from == datetime(2026, 10, 24, 22, 0)
    assert only.occurred_to == datetime(2026, 10, 24, 23, 30)
    assert only.location == "SAMPLE HALL"
    assert only.disposition == "OPEN CASE"


def test_late_report_keeps_occurrence_and_report_dates_apart() -> None:
    row = incident(reported="10/25/2026", start="02/01/2026 00:00:00", end="05/31/2026 23:59:00")
    (only,) = parse_crime_log(page(section("Bloomington", row))).incidents
    assert only.date_reported == date(2026, 10, 25)
    assert only.occurred_from == datetime(2026, 2, 1)
    assert only.occurred_to == datetime(2026, 5, 31, 23, 59)


def test_blank_occurrence_time_is_none() -> None:
    (only,) = parse_crime_log(page(section("Bloomington", incident(end="")))).incidents
    assert only.occurred_to is None


def test_one_case_with_several_offenses() -> None:
    rows = incident(offense="OPERATING WHILE INTOXICATED - ENDANGERMENT") + incident(
        offense="RESISTING LAW ENFORCEMENT"
    )
    log = parse_crime_log(page(section("Bloomington", rows)))
    assert [(i.case_number, i.offense) for i in log.incidents] == [
        ("900001", "OPERATING WHILE INTOXICATED - ENDANGERMENT"),
        ("900001", "RESISTING LAW ENFORCEMENT"),
    ]


def test_count_suffix_and_unicode_dash_are_normalized() -> None:
    row = incident(offense="RAPE \u2013 SEXUAL ASSAULT WITH AN OBJECT X2")
    (only,) = parse_crime_log(page(section("Bloomington", row))).incidents
    assert (only.offense, only.offense_count) == ("RAPE - SEXUAL ASSAULT WITH AN OBJECT", 2)
    assert only.sensitive


def test_identical_repeated_rows_merge_into_a_count() -> None:
    row = incident(offense="BATTERY AGAINST PUBLIC SAFETY OFFICIAL")
    (only,) = parse_crime_log(page(section("Bloomington", row + row))).incidents
    assert only.offense_count == 2


def test_repeated_offense_with_different_details_fails() -> None:
    rows = incident(disposition="OPEN CASE") + incident(disposition="SUSPECT ARRESTED")
    with pytest.raises(ParseError, match="twice"):
        parse_crime_log(page(section("Bloomington", rows)))


def test_no_crimes_table_is_empty() -> None:
    assert parse_crime_log(page(section("Bloomington", NO_CRIMES))).incidents == ()


def test_strips_hidden_characters() -> None:
    row = incident(location="SAMPLE\u200b HALL\u202e", offense="THEFT\u00a0FROM BUILDING")
    (only,) = parse_crime_log(page(section("Bloomington", row))).incidents
    assert (only.location, only.offense) == ("SAMPLE HALL", "THEFT FROM BUILDING")


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("\n   EVANS   SCHOLARS \t ") == "EVANS SCHOLARS"


@pytest.mark.parametrize(
    "html",
    [
        page(section("Columbus", incident())),
        page(section("Bloomington", incident()), section("Bloomington", incident())),
        page(section("Bloomington", incident(), closed=False)),
        page(section("Bloomington", incident(), window="Fall 2026")),
        page(section("Bloomington", incident().replace("Crime Description", "Offense"))),
        page(section("Bloomington", incident() + '<tr role="row"><td>extra</td></tr>')),
        page(section("Bloomington", incident(reported="2026-10-25"))),
        page(section("Bloomington", incident(start="10/24/2026 10:00 PM"))),
        page(section("Bloomington", incident(case=""))),
        page(section("Bloomington", "")),
    ],
    ids=[
        "missing campus",
        "two campus tables",
        "truncated table",
        "bad window",
        "renamed label",
        "stray row",
        "iso date",
        "12h time",
        "blank case number",
        "empty table",
    ],
)
def test_unexpected_shapes_fail_loudly(html: str) -> None:
    with pytest.raises(ParseError):
        parse_crime_log(html)
