"""Activity segments from city centerline rows. Street names are public; shapes are made up."""

import json
from pathlib import Path

import duckdb

from campus_safety.geo import segments

LINE = '{"type":"LineString","coordinates":[[-86.5301234567,39.1665],[-86.529,39.16651]]}'


def row(objectid: int, name: str, low: int, high: int, a: str, b: str) -> dict[str, object]:
    return {
        "objectid": objectid,
        "fullname": name,
        "lowadd": low,
        "highadd": high,
        "lowxst": a,
        "highxst": b,
        "geometry": LINE,
    }


def test_one_segment_per_piece_named_like_the_hand_drawn_ones() -> None:
    found = segments.generate(
        [
            row(7, "E 10th ST", 1400, 1599, "N Eagleson Ave", "N Campbell St"),
            row(3, "E Kirkwood AVE", 400, 499, "S Grant St", "S Dunn St"),
            row(9, "W 10th ST", 710, 799, "W Amy Robinson Dr", "Dead End"),
        ]
    )
    assert found["attribution"] == "Street geometry: City of Bloomington GIS road centerlines"
    assert [(f["id"], f["properties"]["name"]) for f in found["features"]] == [
        ("street_3", "E Kirkwood Ave, 400 block (Grant to Dunn)"),
        ("street_7", "E 10th St, 1400 to 1500 blocks (Eagleson to Campbell)"),
        ("street_9", "W 10th St, 700 block (Amy Robinson to dead end)"),
    ]
    first = found["features"][0]
    assert first["properties"] == {
        "id": "street_3",
        "name": "E Kirkwood Ave, 400 block (Grant to Dunn)",
        "street_objectid": 3,
    }
    assert first["geometry"] == {
        "type": "MultiLineString",
        "coordinates": [[[-86.530123, 39.1665], [-86.529, 39.16651]]],
    }


def test_access_drives_trails_and_unnumbered_pieces_are_left_out() -> None:
    found = segments.generate(
        [
            row(1, "Access Drive to Sample Mall", 100, 199, "N A St", "N B St"),
            row(2, "B-Line Trail", 100, 199, "W 3rd St", "W 4th St"),
            row(3, "E 14th ST", 0, 0, "N Fess Ave", "N Fess Ave"),
            row(4, "E 10th ST", 2200, 2399, "N Jefferson St", "Access Drive To Sample Apartments"),
        ]
    )
    # A cross street that is a business's access drive is never named.
    assert [f["properties"]["name"] for f in found["features"]] == [
        "E 10th St, 2200 to 2300 blocks (Jefferson to an access drive)"
    ]


def test_from_warehouse_reads_silver_streets(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    assert segments.from_warehouse(db) is None  # no warehouse yet
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE SCHEMA silver")
        con.execute(
            "CREATE TABLE silver.geo_streets (objectid BIGINT, fullname VARCHAR, lowadd INT,"
            " highadd INT, lowxst VARCHAR, highxst VARCHAR, geometry VARCHAR)"
        )
        con.execute(
            "INSERT INTO silver.geo_streets VALUES (3, 'E Kirkwood AVE', 400, 499,"
            " 'S Grant St', 'S Dunn St', ?)",
            [LINE],
        )
    found = segments.from_warehouse(db)
    assert found is not None
    assert json.dumps(found)  # serializable for the API
    assert [f["id"] for f in found["features"]] == ["street_3"]
