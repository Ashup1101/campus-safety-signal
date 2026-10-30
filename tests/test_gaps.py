from pathlib import Path

import pytest

from campus_safety import gaps


def test_the_register_loads_and_is_valid() -> None:
    register = gaps.load()
    assert register
    assert {gap.segment.source for gap in register} <= gaps.SOURCES


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "gaps.yaml"
    path.write_text(body)
    return path


GOOD = """
gaps:
  - gap_id: example_gap
    reason: a page went offline
    segment: {source: iu_crime_log, start: 2017-09-04, end: 2024-08-16, fields: [all]}
    closing_source: none public
"""


def test_a_valid_entry(tmp_path: Path) -> None:
    (gap,) = gaps.load(write(tmp_path, GOOD))
    assert gap.gap_id == "example_gap"
    assert (gap.segment.start.isoformat(), gap.segment.fields) == ("2017-09-04", ("all",))  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("example_gap", "Bad Id!"), "bad gap_id"),
        (("source: iu_crime_log", "source: twitter"), "unknown source"),
        (("start: 2017-09-04", "start: 2025-01-01"), "start is after end"),
        (("start: 2017-09-04", "start: soon"), "YYYY-MM-DD"),
        (("fields: [all]", "fields: []"), "fields"),
        (("closing_source: none public", "closing_source: ''"), "closing_source"),
    ],
)
def test_invalid_entries_are_rejected(
    tmp_path: Path, change: tuple[str, str], message: str
) -> None:
    with pytest.raises(gaps.GapRegisterError, match=message):
        gaps.load(write(tmp_path, GOOD.replace(*change)))


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    twice = GOOD + GOOD.replace("gaps:\n", "")
    with pytest.raises(gaps.GapRegisterError, match="duplicate"):
        gaps.load(write(tmp_path, twice))
