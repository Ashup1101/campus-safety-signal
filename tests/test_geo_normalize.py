"""IUPD street strings to (street, side, cross street). Street names are public; strings made up."""

import pytest

from campus_safety.geo.normalize import Segment, parse_segment

KNOWN = {"10TH", "17TH", "3RD", "EAGLESON", "FEE", "DUNN", "INDIANA", "JONES", "KIRKWOOD"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10TH STREET/EAST OF JORDA", Segment("10TH", "east", "EAGLESON")),
        ("10TH STREET/WEST OF JORDAN", Segment("10TH", "west", "EAGLESON")),
        ("1OTH STREET/EAST OF FEE LANE", Segment("10TH", "east", "FEE")),
        ("DUNN STREET/SOUTH OF 10TH", Segment("DUNN", "south", "10TH")),
        ("FEE LANE/NORTH OF 10TH ST", Segment("FEE", "north", "10TH")),
        ("3RD STREET/W OF EAGLESON", Segment("3RD", "west", "EAGLESON")),
    ],
)
def test_parses_known_streets(text: str, expected: Segment) -> None:
    assert parse_segment(text, KNOWN) == expected


@pytest.mark.parametrize(
    "text",
    [
        "MCNUTT QUAD",  # a place, not a street stretch
        "10TH STREET/NEAR JORDAN",  # no side
        "NOWHERE ROAD/EAST OF FEE",  # unknown street
        "10TH STREET/EAST OF J",  # too short to tell which street
        "10TH STREET/EAST OF 10TH",  # a street cannot cross itself
    ],
)
def test_unknown_or_ambiguous_strings_are_never_guessed(text: str) -> None:
    assert parse_segment(text, KNOWN) is None


def test_a_cut_off_name_must_match_one_street_only() -> None:
    assert parse_segment("10TH STREET/EAST OF JO", {"10TH", "JONES", "JORDAN"}) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("JORDAN AVENUE/NORTH OF 10", Segment("EAGLESON", "north", "10TH")),  # bare number
        ("INDIANA AVENUE/SOUTH OF 1OTH STR", Segment("INDIANA", "south", "10TH")),  # cut-off type
        ("46 BYPASS/NORTH OF 17TH STREET", Segment("STATE ROAD 45 46 BYPASS", "north", "17TH")),
    ],
)
def test_bare_numbers_cut_off_types_and_old_names(text: str, expected: Segment) -> None:
    known = KNOWN | {"STATE ROAD 45 46 BYPASS"}
    assert parse_segment(text, known) == expected


def test_a_bare_number_is_only_its_own_ordinal() -> None:
    assert parse_segment("DUNN STREET/NORTH OF 1", {"DUNN", "1ST", "10TH"}) == Segment(
        "DUNN", "north", "1ST"
    )
    assert parse_segment("DUNN STREET/NORTH OF 12", {"DUNN", "12TH", "11TH"}) == Segment(
        "DUNN", "north", "12TH"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EAGLESON AVE NORTH OF 10TH ST", Segment("EAGLESON", "north", "10TH")),  # no slash
        ("KIRKWOOD WEST OF DUNN", Segment("KIRKWOOD", "west", "DUNN")),
        # The log merges repeated values with commas: the first one is the location.
        (
            "FEE LANE/NORTH OF 10TH ST, NORTH OF 10TH ST FEE LANE, GATE 13",
            Segment("FEE", "north", "10TH"),
        ),
        ("DISCOVERY PARKWAY/NORTH OF 10TH", Segment("DISCOVERY", "north", "10TH")),
    ],
)
def test_other_ways_the_log_writes_a_stretch(text: str, expected: Segment) -> None:
    assert parse_segment(text, KNOWN | {"DISCOVERY"}) == expected
