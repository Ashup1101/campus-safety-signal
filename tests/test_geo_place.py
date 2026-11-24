"""Placing IUPD location strings on a made-up street grid (real street names, invented shapes).

17TH  ---------+-----------
          FEE  |  EAGLESON |
10TH  ----1----+-----2-----+ UNION
               |  3 (south of 10TH)
"""

import pytest

from campus_safety.geo.place import (
    AddressPoint,
    Network,
    Piece,
    Placement,
    place_address,
    place_segment,
)

A, B, C = -86.520, -86.515, -86.510  # FEE, EAGLESON, UNION
TENTH, THIRD, SEVENTEENTH = 39.170, 39.165, 39.175


def piece(objectid: int, street: str, low: str, high: str, *points: tuple[float, float]) -> Piece:
    return Piece(objectid, street, low, high, None, None, ((*points,),))


NETWORK = Network(
    [
        piece(1, "10TH", "FEE", "EAGLESON", (A, TENTH), (B, TENTH)),
        # Drawn from the far end back to the corner: the corner end is found from geometry.
        piece(2, "10TH", "EAGLESON", "UNION", (C, TENTH), (B, TENTH)),
        piece(3, "EAGLESON", "3RD", "10TH", (B, THIRD), (B, TENTH)),
        piece(4, "EAGLESON", "10TH", "17TH", (B, TENTH), (B, SEVENTEENTH)),
        piece(5, "FEE", "10TH", "17TH", (A, TENTH), (A, SEVENTEENTH)),
        piece(6, "UNION", "10TH", "17TH", (C, TENTH), (C, SEVENTEENTH)),
        piece(7, "17TH", "FEE", "UNION", (A, SEVENTEENTH), (C, SEVENTEENTH)),
        piece(8, "3RD", "EAGLESON", "UNION", (B, THIRD), (C, THIRD)),
    ],
    [],
)


@pytest.mark.parametrize(
    ("text", "objectid", "lon", "lat"),
    [
        ("10TH STREET/EAST OF JORDA", 2, -86.5125, TENTH),
        ("10TH STREET/WEST OF JORDAN", 1, -86.5175, TENTH),
        ("JORDAN AVENUE/NORTH OF 10", 4, B, 39.1725),
        ("JORDAN AVENUE/SOUTH OF 1OTH STR", 3, B, 39.1675),
        ("10TH STREET/EAST OF EAGLESON", 2, -86.5125, TENTH),
    ],
)
def test_street_stretch_is_the_piece_on_the_named_side_of_the_corner(
    text: str, objectid: int, lon: float, lat: float
) -> None:
    assert place_segment(text, NETWORK) == Placement("segment", lat, lon, objectid)


@pytest.mark.parametrize(
    "text",
    [
        "FEE LANE/SOUTH OF 10TH",  # no piece of Fee south of 10th in the network
        "10TH STREET/NORTH OF JORDAN",  # 10th runs east-west: north of the corner is not on it
        "10TH STREET/EAST OF UNION",  # the network ends at Union
        "17TH STREET/EAST OF EAGLESON",  # the piece does not list Eagleson as an end
        "WOODLAWN AVENUE/NORTH OF",  # no cross street
        "MCNUTT QUAD",  # a building, not a street stretch
    ],
)
def test_anything_unclear_stays_unplaced(text: str) -> None:
    assert place_segment(text, NETWORK) is None


def test_the_corner_must_touch_the_cross_street() -> None:
    far = Network([piece(1, "10TH", "FEE", "EAGLESON", (A, TENTH), (B, TENTH))], [])
    # Eagleson is named as an end but no piece of Eagleson exists to find the corner.
    assert place_segment("10TH STREET/WEST OF EAGLESON", far) is None


ADDRESSES = Network(
    [],
    [
        AddressPoint(502, "E", "KIRKWOOD", 39.1663, -86.5280),
        AddressPoint(502, "W", "KIRKWOOD", 39.1663, -86.5400),
        AddressPoint(509, "E", "3RD", 39.1646, -86.5278),
        AddressPoint(1200, "N", "EAGLESON", 39.1775, -86.5119),
    ],
)


@pytest.mark.parametrize(
    ("text", "lat", "lon"),
    [
        ("502 E. KIRKWOOD", 39.1663, -86.5280),
        ("509 E 3RD, 509 E. 3RD, 1150 S CLARIZZ L348", 39.1646, -86.5278),  # first value
        ("1200 N Jordan - Non-campus building or property", 39.1775, -86.5119),  # old name
        ("509 3RD STREET", 39.1646, -86.5278),  # one 509 on 3rd: no direction needed
    ],
)
def test_an_address_is_its_city_address_point(text: str, lat: float, lon: float) -> None:
    assert place_address(text, ADDRESSES) == Placement("address", lat, lon, None)


@pytest.mark.parametrize(
    "text",
    [
        "502 KIRKWOOD AVE",  # East and West 502 both exist
        "509 W 3RD",  # the direction does not match
        "1500 N. JORDAN AVENUE",  # no such address point
        "SAMPLE HALL",
    ],
)
def test_an_address_without_one_clear_point_stays_unplaced(text: str) -> None:
    assert place_address(text, ADDRESSES) is None
