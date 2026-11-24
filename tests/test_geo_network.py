"""Street network rows from the city's layers. Made-up features and names."""

import json
from datetime import UTC, datetime

import pytest

from campus_safety.geo import streets
from campus_safety.geo.normalize import street_key
from campus_safety.lake import bronze


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("E 10TH ST", "10TH"),
        ("10th Street", "10TH"),
        ("N JORDAN AVE", "JORDAN"),
        ("FEE LN", "FEE"),
        ("E SAMPLE GATES RD", "SAMPLE GATES"),
        ("ST", "ST"),
        ("N. Indiana Ave.", "INDIANA"),
    ],
)
def test_street_key(name: str, key: str) -> None:
    assert street_key(name) == key


def manifest(source: str) -> bronze.Manifest:
    return bronze.Manifest(
        source, "bronze/k", "https://x", datetime(2026, 11, 24, tzinfo=UTC), "0" * 64, 200, "r1"
    )


def layer(*features: dict[str, object]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": list(features)}).encode()


def test_street_rows_keep_lines_with_names_only() -> None:
    line = {"type": "LineString", "coordinates": [[-86.53, 39.17], [-86.52, 39.17]]}
    body = layer(
        {
            "properties": {
                "objectid": 1,
                "fullname": "E 10TH ST",
                "lowadd": 100,
                "highadd": 199,
                "lowxst": "N WALNUT ST",
            },
            "geometry": line,
        },
        {"properties": {"objectid": 2, "fullname": ""}, "geometry": line},
        {
            "properties": {"objectid": 3, "fullname": "E 3RD ST"},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        },
    )
    rows = streets.street_rows(manifest("city_gis_streets"), body)
    assert [(r[0], r[2], r[3], r[5]) for r in rows] == [(1, "10TH", 100, "N WALNUT ST")]


def test_intersections_split_into_two_street_keys() -> None:
    point = {"type": "Point", "coordinates": [-86.52, 39.17]}
    body = layer(
        {"properties": {"OBJECTID": 7, "intname": "E 10TH ST & N JORDAN AVE"}, "geometry": point},
        {"properties": {"OBJECTID": 8, "intname": "NO AMPERSAND"}, "geometry": point},
    )
    rows = streets.intersection_rows(manifest("city_gis_intersections"), body)
    assert [(r[0], r[2], r[3], r[4], r[5]) for r in rows] == [(7, "10TH", "JORDAN", 39.17, -86.52)]


def test_addresses_one_row_per_street_address() -> None:
    def address(number: object, unit: str) -> dict[str, object]:
        props = {
            "street_number": number,
            "street_direction": "E",
            "street_name": "KIRKWOOD",
            "street_suffix": "AVE",
            "lat": 39.166,
            "lon": -86.53,
            "unit": unit,
        }
        return {"properties": props, "geometry": None}

    rows = streets.address_rows(
        manifest("city_gis_addresses"),
        layer(address(502, "1"), address(502, "2"), address(None, "x")),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(502, "E", "KIRKWOOD")]
