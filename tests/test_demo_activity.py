"""Activity levels per street segment and time window. Made-up incidents."""

import re
from datetime import date, datetime

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
