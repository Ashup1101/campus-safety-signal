"""Placing IUPD location strings on a made-up street grid (real street names, invented shapes).

17TH  ---------+-----------
          FEE  |  EAGLESON |
10TH  ----1----+-----2-----+ UNION
               |  3 (south of 10TH)
"""

import pytest

from campus_safety.geo.place import Network, Piece, Placement, place_segment

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
