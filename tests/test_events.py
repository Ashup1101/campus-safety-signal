"""Event nights and night-time windows."""

from datetime import date, datetime
from pathlib import Path

import pytest

from campus_safety import events

NIGHTS = frozenset({date(2026, 10, 31)})


def test_a_night_belongs_to_the_date_it_starts() -> None:
    assert events.night_of(datetime(2026, 11, 1, 1, 30)) == date(2026, 10, 31)
    assert events.night_of(datetime(2026, 10, 31, 23, 0)) == date(2026, 10, 31)
    assert events.night_of(datetime(2026, 10, 31, 12, 0)) == date(2026, 10, 31)


@pytest.mark.parametrize(
    ("hour", "late"), [(21, False), (22, True), (1, True), (3, True), (4, False), (12, False)]
)
def test_late_night(hour: int, late: bool) -> None:
    assert events.is_late_night(datetime(2026, 3, 3, hour, 0)) is late


def test_event_night_needs_the_date_and_the_hours() -> None:
    assert events.is_event_night(datetime(2026, 10, 31, 18, 0), NIGHTS)
    assert events.is_event_night(datetime(2026, 11, 1, 1, 30), NIGHTS)
    assert not events.is_event_night(datetime(2026, 10, 31, 17, 59), NIGHTS)
    assert not events.is_event_night(datetime(2026, 11, 1, 4, 0), NIGHTS)
    assert not events.is_event_night(datetime(2026, 11, 7, 23, 0), NIGHTS)
    assert events.high_alert(datetime(2026, 10, 31, 19, 0), NIGHTS)
    assert not events.high_alert(datetime(2026, 11, 7, 19, 0), NIGHTS)


def test_aware_times_are_read_in_bloomington() -> None:
    utc = datetime.fromisoformat("2026-11-01T05:30:00+00:00")  # 01:30 EDT
    assert events.is_event_night(utc, NIGHTS)


def test_calendar_loads_and_validates(tmp_path: Path) -> None:
    assert date(2026, 4, 25) in events.event_nights()
    bad = tmp_path / "events.yaml"
    bad.write_text("events:\n  - event_id: x\n    name: X\n    nights: [soon]\n")
    with pytest.raises(ValueError, match="nights"):
        events.load(bad)
