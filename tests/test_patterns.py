"""Phase 5: levels, nightly baselines, anomaly detection, forecasts, detector scoring."""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from campus_safety.lake.storage import FileLake
from campus_safety.patterns import baselines
from campus_safety.patterns.categories import category, is_serious
from campus_safety.patterns.cli import main
from campus_safety.patterns.levels import Observation, level, levels, reason

AS_OF = datetime(2026, 11, 2, 9, 0)
NIGHTS = frozenset({date(2026, 10, 31)})


def quiet_history(place: str, weeks: int = 12, per_night: int = 1) -> list[Observation]:
    """One minor incident every night at 23:00 for `weeks` weeks before AS_OF."""
    found = []
    for d in range(1, weeks * 7 + 1):
        night = AS_OF.date() - timedelta(days=d)
        for n in range(per_night):
            found.append(
                Observation(
                    place,
                    datetime.combine(night, datetime.min.time()) + timedelta(hours=23, minutes=n),
                    "THEFT - ALL OTHER",
                    "medium",
                )
            )
    return found


def test_categories_and_levels_match_the_demo_rules() -> None:
    assert category("ROBBERY") == "robbery" and category("WHATEVER") == "other incident"
    assert is_serious("THEFT", "high") and is_serious("ROBBERY", "medium")
    assert not is_serious("THEFT", "medium")
    assert (level(0, 2), level(0, 3), level(1, 1), level(2, 2), level(0, 8)) == (
        "quiet", "elevated", "elevated", "high", "high",
    )  # fmt: skip
    from collections import Counter

    assert (
        reason("event_night", Counter({"shooting": 2}), {2026})
        == "2 shootings on event nights in 2026"
    )
    assert reason("late_night", Counter(), set()).startswith("Nothing recorded on late nights")


def test_levels_cover_every_place_and_window() -> None:
    rows = levels(quiet_history("TETER QUAD", weeks=2), AS_OF, NIGHTS)
    assert [(r.place, r.window, r.level) for r in rows] == [
        ("TETER QUAD", "late_night", "high"),
        ("TETER QUAD", "event_night", "quiet"),
    ]
    assert rows[0].incidents == 14 and rows[0].serious == 0
    assert "safe" not in rows[0].reason and "risk" not in rows[0].reason


def test_poisson_tail() -> None:
    assert baselines.poisson_tail(0, 1.0) == 1.0
    assert baselines.poisson_tail(3, 0.0) == 0.0
    assert abs(baselines.poisson_tail(1, 1.0) - (1 - 2.718281828**-1)) < 1e-6
    assert baselines.poisson_tail(6, 1.0) < 0.001


def test_detect_flags_a_spike_but_not_an_expected_event_night() -> None:
    history = quiet_history("TETER QUAD")
    spike_night = AS_OF.date() - timedelta(days=3)
    history += [
        Observation(
            "TETER QUAD",
            datetime.combine(spike_night, datetime.min.time()) + timedelta(hours=22, minutes=m),
            "BATTERY NO INJURY",
            "medium",
        )
        for m in range(6)
    ]
    found = baselines.detect(history, NIGHTS, AS_OF)
    assert [(a.place, a.night, a.observed) for a in found] == [("TETER QUAD", spike_night, 7)]
    assert found[0].expected == 1.0 and found[0].p_value < 0.01
    # The same count on the event night, with a learned multiplier, is far less surprising.
    busy = quiet_history("TETER QUAD") + [
        Observation("TETER QUAD", datetime(2026, 10, 31, 23, m), "THEFT - ALL OTHER", "medium")
        for m in range(2)
    ]
    multiplier = baselines.event_multiplier(
        baselines.nightly_counts(busy), NIGHTS, date(2026, 8, 1), AS_OF.date()
    )
    assert multiplier >= 3.0
    assert baselines.detect(busy, NIGHTS, AS_OF) == []


def test_forecast_and_baselines() -> None:
    history = quiet_history("TETER QUAD") + quiet_history("WRIGHT QUAD", per_night=2)
    nights = frozenset({AS_OF.date() + timedelta(days=3)})
    found = baselines.forecast(history, nights, AS_OF, days=4)
    assert len(found) == 8
    teter = {f.night: f for f in found if f.place == "TETER QUAD"}
    assert teter[AS_OF.date() + timedelta(days=1)].expected == 1.0
    assert teter[AS_OF.date() + timedelta(days=3)].event_night
    assert teter[AS_OF.date() + timedelta(days=3)].expected >= 1.0
    rows = baselines.baselines(history, AS_OF)
    assert len(rows) == 14 and {r.mean_per_night for r in rows if r.place == "WRIGHT QUAD"} == {2.0}
    assert baselines.detect([], NIGHTS, AS_OF) == [] and baselines.forecast([], NIGHTS, AS_OF) == []


def test_score_against_planted_spikes() -> None:
    night = date(2026, 10, 20)
    detected = [
        baselines.Anomaly("A", night, 5, 1.0, 0.001, False),
        baselines.Anomaly("B", night, 4, 1.0, 0.01, False),
    ]
    planted = [
        ("A", datetime(2026, 10, 20, 18), datetime(2026, 10, 22, 4)),
        ("C", datetime(2026, 10, 1, 18), datetime(2026, 10, 2, 4)),
    ]
    result = baselines.score(detected, planted)
    assert (result.planted, result.detected, result.hits, result.false_alarms) == (2, 2, 1, 1)
    assert (result.precision, result.recall) == (0.5, 0.5)


def warehouse(path: Path, observations: list[Observation]) -> Path:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA gold; CREATE SCHEMA silver")
        con.execute(
            "CREATE TABLE gold.incidents_real (location_text VARCHAR, occurred_from TIMESTAMP,"
            " incident_type VARCHAR, severity_tier VARCHAR, is_sensitive BOOLEAN,"
            " location_type VARCHAR)"
        )
        con.executemany(
            "INSERT INTO gold.incidents_real VALUES (?, ?, ?, ?, false, 'place')",
            [(o.place, o.occurred_at, o.incident_type, o.severity_tier) for o in observations],
        )
        con.execute(
            "CREATE TABLE silver.synthetic_incidents (gap_id VARCHAR, seed BIGINT,"
            " location VARCHAR, occurred_at TIMESTAMP, incident_type VARCHAR, severity VARCHAR)"
        )
        con.execute(
            "CREATE TABLE silver.synthetic_anomalies (gap_id VARCHAR, seed BIGINT, zone_id VARCHAR,"
            " start_at TIMESTAMP, end_at TIMESTAMP, kind VARCHAR)"
        )
        spike_night = AS_OF.date() - timedelta(days=10)  # not an event night
        rows = [
            ("g", 1, o.place, o.occurred_at, o.incident_type, o.severity_tier) for o in observations
        ]
        rows += [
            (
                "g",
                1,
                "TETER QUAD",
                datetime.combine(spike_night, datetime.min.time()) + timedelta(hours=22, minutes=m),
                "BATTERY NO INJURY",
                "medium",
            )
            for m in range(6)
        ]
        con.executemany("INSERT INTO silver.synthetic_incidents VALUES (?, ?, ?, ?, ?, ?)", rows)
        con.execute(
            "INSERT INTO silver.synthetic_anomalies VALUES ('g', 1, 'TETER QUAD', ?, ?, 'spike')",
            [
                datetime.combine(spike_night, datetime.min.time()) + timedelta(hours=18),
                datetime.combine(spike_night + timedelta(days=1), datetime.min.time())
                + timedelta(hours=4),
            ],
        )
    return path


def test_cli_run_and_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lake = FileLake(tmp_path / "lake")
    monkeypatch.setenv("LAKE_URI", lake.uri)
    caplog.set_level(logging.INFO)
    db = warehouse(tmp_path / "w.duckdb", quiet_history("TETER QUAD"))
    base = ["--warehouse", str(db), "--work-dir", str(tmp_path / "work")]
    assert main([*base, "run", "--as-of", AS_OF.isoformat()]) == 0
    assert (
        "84 observations -> 2 level rows (1 high), 0 anomalies, 7 forecast rows, 7 baselines"
        in caplog.text
    )
    assert sorted(lake.keys("gold/")) == [
        "gold/activity_levels.parquet",
        "gold/anomalies.parquet",
        "gold/baselines.parquet",
        "gold/forecasts.parquet",
    ]
    assert main([*base, "score", "g", "1"]) == 0
    assert (
        "1 planted spikes, 1 detected nights, 1 spikes found, 0 false alarms, precision 1.00,"
        " recall 1.00" in caplog.text
    )
    assert main([*base, "score", "g", "2"]) == 1
    assert main(["--warehouse", str(tmp_path / "missing.duckdb"), "run"]) == 1
