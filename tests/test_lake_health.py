"""Source health for the console: fresh, stale, failing or never, from what the lake stores.
Made-up pages and a fixed clock."""

from datetime import timedelta
from pathlib import Path

import pytest
from crime_log_html import incident
from test_lake_transform import DAY_1, bloomington, snapshot

from campus_safety.lake import health
from campus_safety.lake.storage import FileLake
from campus_safety.lake.transform import transform

CADENCES = [
    health.Cadence("iu_crime_log", "IU crime log", 36),
    health.Cadence("news_ipm", "WFIU/IPM news", 72),
]


def states(lake: FileLake, hours: float) -> dict[str, tuple[str, str | None]]:
    found = health.report(lake, CADENCES, DAY_1 + timedelta(hours=hours))
    return {row["source"]: (row["state"], row["error_kind"]) for row in found}


def test_states_follow_the_newest_stored_copy_and_its_parse(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    snapshot(lake, 0, bloomington(incident()))
    transform(lake, tmp_path / "work")
    assert states(lake, 10) == {
        "iu_crime_log": ("fresh", None),
        "news_ipm": ("never", None),
    }
    assert states(lake, 48)["iu_crime_log"] == ("stale", None)  # past 36 hours
    snapshot(lake, 1, "<html>redesigned</html>")
    transform(lake, tmp_path / "work")
    assert states(lake, 30)["iu_crime_log"] == ("failing", "parse_error")
    row = health.report(lake, CADENCES, DAY_1 + timedelta(hours=30))[0]
    assert row["last_stored_at"] == (DAY_1 + timedelta(days=1)).isoformat()
    assert row["copies"] == 2 and row["expected_hours"] == 36


def test_the_cadence_config_names_each_source_once(tmp_path: Path) -> None:
    found = health.load()
    assert found and len({c.source for c in found}) == len(found)
    assert all(c.expected_hours > 0 and c.label for c in found)
    bad = tmp_path / "sources.yaml"
    bad.write_text("sources:\n  iu_crime_log: {label: IU, expected_hours: 0}\n")
    with pytest.raises(ValueError, match="expected_hours"):
        health.load(bad)
