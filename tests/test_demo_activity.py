"""Activity levels per street segment and time window. Made-up incidents."""

import json
import re
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest
from build_demo_segments import SEGMENTS

from campus_safety.patterns.categories import category as category_of
from campus_safety.patterns.categories import plural
from demo_server import activity
from demo_server.store import Activity

NIGHTS = frozenset({date(2026, 4, 25), date(2026, 10, 31)})
NOW = datetime(2026, 11, 2, 12, 0)
ALL = activity.segments(activity.load_geojson())


def shooting(at: datetime, segment: str = "kirkwood_400") -> activity.Incident:
    return activity.Incident(at, "shooting", True, (segment,))


def theft(at: datetime, segment: str = "kirkwood_400") -> activity.Incident:
    return activity.Incident(at, "theft", False, (segment,))


def by_window(rows: list[Activity], segment: str) -> dict[str, Activity]:
    return {r.window: r for r in rows if r.segment_id == segment}


def test_committed_segments_match_the_builder() -> None:
    geojson = activity.load_geojson()
    assert [f["properties"]["id"] for f in geojson["features"]] == [s["id"] for s in SEGMENTS]
    assert [f["properties"]["match"] for f in geojson["features"]] == [s["match"] for s in SEGMENTS]
    assert "City of Bloomington" in geojson["attribution"]


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("412 E. KIRKWOOD", {"kirkwood_400"}),
        ("400 BLK E KIRKWOOD", {"kirkwood_400"}),
        ("ALL OTHER NON-UNIVERSITY - KIRKWOOD @ DUNN", {"kirkwood_400", "kirkwood_500"}),
        ("ALL OTHER NON-UNIVERSITY, , KIRKWOOD AND GRANT", {"kirkwood_300", "kirkwood_400"}),
        ("10TH STREET/WEST OF EAGLESON", {"e10th_west_eagleson"}),
        ("17TH STREET/WEST OF EAGLESON", set()),
        ("7TH STREET/EAST OF EAGLESON", {"e7th_east_eagleson"}),
        ("INDIANA AVENUE/SOUTH OF 1OTH STR", {"indiana_south_10th"}),
        ("BALLANTINE HALL, 1020 E. KIRKWOOD", set()),
    ],
)
def test_location_phrases_match_segments(location: str, expected: set[str]) -> None:
    assert {s.id for s in ALL if s.matches(location)} == expected


def test_two_event_night_shootings_make_a_high_segment() -> None:
    incidents = [shooting(datetime(2026, 4, 26, 0, 25)), shooting(datetime(2026, 11, 1, 1, 30))]
    rows = by_window(activity.levels(["kirkwood_400"], incidents, NOW, NIGHTS), "kirkwood_400")
    assert rows["event_night"].level == "high"
    assert rows["event_night"].reason == "2 shootings on event nights in 2026"
    assert rows["late_night"].level == "high"


def test_levels_count_volume_and_ignore_other_windows_and_old_incidents() -> None:
    incidents = [
        theft(datetime(2026, 3, 3, 23, 0)),
        theft(datetime(2025, 3, 3, 23, 0)),
        theft(datetime(2024, 3, 3, 1, 0)),
        theft(datetime(2026, 3, 3, 14, 0)),  # afternoon: no window
        shooting(datetime(2019, 3, 3, 23, 0)),  # older than the lookback
    ]
    rows = by_window(activity.levels(["kirkwood_400"], incidents, NOW, NIGHTS), "kirkwood_400")
    assert (rows["late_night"].level, rows["late_night"].incidents) == ("elevated", 3)
    assert rows["late_night"].reason == "3 thefts on late nights 2024-2026"
    assert rows["event_night"].level == "quiet"
    assert rows["event_night"].reason == "Nothing recorded on event nights in the data we hold"


def test_reasons_never_use_alarming_words() -> None:
    incidents = [shooting(datetime(2026, 11, 1, 1, 30)), theft(datetime(2026, 11, 1, 2, 0))]
    rows = activity.levels([s.id for s in ALL], incidents, NOW, NIGHTS)
    assert not any(re.search(r"\b(safe|unsafe|risk|danger)", r.reason, re.I) for r in rows)


@pytest.mark.parametrize(
    ("incident_type", "category"),
    [
        ("ROBBERY - ARMED", "robbery"),
        ("DRUNK DRIVING - DRIVING UNDER THE INFLUENCE", "traffic incident"),
        ("LARCENY-THEFT - FROM BUILDINGS", "theft"),
        ("ILLEGAL CONSUMPTION/POSSESSION OF ALCOHOL BY MINOR", "alcohol incident"),
        ("FIRE ALARM", "other incident"),
        ("UNLAWFUL CARRYING OF A HANDGUN", "weapons incident"),
        ("RESISTING LAW ENFORCEMENT", "police obstruction report"),
    ],
)
def test_category(incident_type: str, category: str) -> None:
    assert category_of(incident_type) == category


def test_plural() -> None:
    assert [plural("robbery", 2), plural("theft", 1)] == ["robberies", "theft"]


def city_warehouse(path: Path, points: list[tuple[str, str, datetime]]) -> Path:
    """A warehouse with one city street piece (the hand-drawn 400 block's line) and points."""
    hand = next(
        f for f in activity.load_geojson()["features"] if f["properties"]["id"] == "kirkwood_400"
    )
    line = {"type": "LineString", "coordinates": hand["geometry"]["coordinates"][0]}
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA silver; CREATE SCHEMA gold")
        con.execute(
            "CREATE TABLE silver.geo_streets (objectid BIGINT, fullname VARCHAR, lowadd INT,"
            " highadd INT, lowxst VARCHAR, highxst VARCHAR, geometry VARCHAR)"
        )
        con.execute(
            "INSERT INTO silver.geo_streets VALUES (3, 'E Kirkwood AVE', 400, 499, 'S Grant St',"
            " 'S Dunn St', ?), (8, 'S Dunn ST', 100, 199, 'E Kirkwood Ave', 'E 4th St', ?)",
            [
                json.dumps(line),
                '{"type":"LineString","coordinates":[[-86.5283,39.1666],[-86.5283,39.1650]]}',
            ],
        )
        con.execute(
            "CREATE TABLE gold.incident_points (incident_type VARCHAR, severity_tier VARCHAR,"
            " date_reported DATE, occurred_from TIMESTAMP, precision VARCHAR, lat DOUBLE,"
            " lon DOUBLE, street_objectid BIGINT)"
        )
        for kind, tier, at in points:
            con.execute(
                "INSERT INTO gold.incident_points"
                " VALUES (?, ?, ?, ?, 'segment', 39.1666, -86.529, 3)",
                [kind, tier, at.date(), at],
            )
    return path


def test_hand_drawn_segments_when_the_warehouse_has_no_street_network(tmp_path: Path) -> None:
    geojson = activity.load_segments(tmp_path / "missing.duckdb")
    assert [f["id"] for f in geojson["features"]] == [s["id"] for s in SEGMENTS]
    assert not activity.is_generated(geojson)


def test_generated_segments_count_incident_points_and_hand_entered_incidents(
    tmp_path: Path,
) -> None:
    db = city_warehouse(
        tmp_path / "w.duckdb",
        [
            ("ROBBERY", "high", datetime(2026, 3, 3, 23, 0)),
            ("THEFT FROM BUILDING LESS THAN $750", "low", datetime(2026, 3, 4, 23, 30)),
        ],
    )
    geojson = activity.load_segments(db)
    assert activity.is_generated(geojson)
    assert [f["id"] for f in geojson["features"]] == ["street_3", "street_8"]
    hand_entered = [shooting(datetime(2026, 4, 26, 0, 25))]  # on hand-drawn kirkwood_400
    incidents = activity.point_incidents(db) + activity.translate(
        hand_entered, activity.load_geojson(), geojson
    )
    assert [i.segments for i in incidents] == [("street_3",)] * 3  # never the cross street
    rows = activity.levels(["street_3", "street_8"], incidents, NOW, NIGHTS)
    late = by_window(rows, "street_3")["late_night"]
    assert (late.level, late.incidents, late.serious) == ("high", 3, 2)
    assert by_window(rows, "street_8")["late_night"].level == "quiet"


def test_hand_entered_incidents_move_to_one_piece_of_the_same_street_only() -> None:
    hand = {
        "features": [
            {
                "properties": {"id": "e7th", "name": "E 7th St, Eagleson Ave to Union St"},
                "geometry": {"coordinates": [[[-86.52, 39.17], [-86.51, 39.17]]]},
            }
        ]
    }

    def piece(segment_id: str, name: str, *line: list[float]) -> dict[str, object]:
        return {
            "properties": {"id": segment_id, "name": name},
            "geometry": {"coordinates": [list(line)]},
        }

    one = {
        "features": [
            piece(
                "street_1",
                "E 7th St, 1400 block (Eagleson to Union)",
                [-86.52, 39.17],
                [-86.51, 39.17],
            ),
            # A short cross-street piece whose middle sits on the 7th St line: never counted.
            piece(
                "street_2",
                "N Union St, 200 block (7th to 7th)",
                [-86.51, 39.1699],
                [-86.51, 39.1701],
            ),
        ]
    }
    two = {
        "features": [
            piece(
                "street_1",
                "E 7th St, 1400 block (Eagleson to Swain)",
                [-86.52, 39.17],
                [-86.515, 39.17],
            ),
            piece(
                "street_3",
                "E 7th St, 1500 block (Swain to Union)",
                [-86.515, 39.17],
                [-86.51, 39.17],
            ),
        ]
    }
    hit = [shooting(datetime(2026, 4, 26, 0, 25), "e7th")]
    assert [i.segments for i in activity.translate(hit, hand, one)] == [("street_1",)]
    # Two pieces along the stretch: which one is unknown, so the incident is not guessed onto both.
    assert activity.translate(hit, hand, two) == []


def test_tonight_comes_from_the_police_zone_each_segment_lies_in(tmp_path: Path) -> None:
    db = city_warehouse(tmp_path / "w.duckdb", [])
    night = date(2026, 10, 31)
    box = [[-86.5300, 39.1660], [-86.5286, 39.1660], [-86.5286, 39.1670], [-86.5300, 39.1670]]
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE silver.geo_law_zones (zonecode VARCHAR, geometry VARCHAR)")
        con.execute(
            "INSERT INTO silver.geo_law_zones VALUES ('LB408', ?)",
            [json.dumps({"type": "Polygon", "coordinates": [[*box, box[0]]]})],
        )
        con.execute(
            'CREATE TABLE gold.tonight (zonecode VARCHAR, night DATE, "window" VARCHAR,'
            " expected DOUBLE, level VARCHAR, method VARCHAR, reason VARCHAR)"
        )
        con.execute(
            "INSERT INTO gold.tonight VALUES ('LB408', ?, 'late_night', 2.0, 'high', 'rule',"
            " 'Expected much busier than usual: Halloween weekend')",
            [night],
        )
    geojson = activity.load_segments(db)
    rows = activity.tonight_rows(db, geojson, night)
    # The Dunn St piece lies outside the zone: it gets no tonight level.
    assert [(r.segment_id, r.window, r.level) for r in rows] == [("street_3", "tonight", "high")]
    assert rows[0].reason == (
        "Expected much busier than usual: Halloween weekend (city calls for service, simple rule)"
    )
    assert activity.tonight_rows(db, geojson, date(2026, 11, 25)) == []  # never invented
    assert activity.tonight_rows(tmp_path / "none.duckdb", geojson, night) == []
