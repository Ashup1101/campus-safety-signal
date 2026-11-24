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
