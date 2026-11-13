"""Phase 4: seeded synthetic patches, labeled anomalies, eval sets, and the gap report."""

import logging
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from campus_safety.gaps import Gap, Segment
from campus_safety.iu_crime_log.classify import is_sensitive
from campus_safety.lake.storage import FileLake
from campus_safety.news.extract import RulesExtractor
from campus_safety.synthetic import generate, news, profile, store, traces
from campus_safety.synthetic.cli import main

GAP = Gap(
    "test_gap",
    "made up",
    Segment("iu_crime_log", date(2019, 9, 1), date(2019, 12, 31), ("all",)),
    "none",
)
NIGHTS = frozenset({date(2019, 10, 31)})


def test_generation_is_seeded_and_labeled() -> None:
    first, anomalies = generate.generate(GAP, profile.default(), 7, NIGHTS)
    again, _ = generate.generate(GAP, profile.default(), 7, NIGHTS)
    other, _ = generate.generate(GAP, profile.default(), 8, NIGHTS)
    assert first == again and first != other
    days = (GAP.segment.end - GAP.segment.start).days + 1  # type: ignore[operator]
    expected = profile.DEFAULT_YEARLY_TOTAL * days / 365
    assert 0.6 * expected < len(first) < 1.8 * expected  # anomalies add rows on top
    assert all(i.case_number.startswith("SYN-test_gap-7-") for i in first)
    assert not any(is_sensitive(i.incident_type) for i in first)
    assert {i.location for i in first} <= set(profile.DEFAULT_LOCATIONS)
    assert all(GAP.segment.start <= i.occurred_at.date() <= GAP.segment.end for i in first)  # type: ignore[operator]
    assert len(anomalies) == generate.ANOMALIES_PER_YEAR
    assert {a.kind for a in anomalies} <= {"spike", "lull"}
    labeled = {i.anomaly_id for i in first if i.anomaly_id}
    assert labeled <= {a.anomaly_id for a in anomalies}
    assert any(i.event_night for i in first)
    assert len({i.case_number for i in first}) == len(first)


def test_spikes_raise_their_zone_and_the_profile_refuses_sensitive_labels() -> None:
    incidents, anomalies = generate.generate(GAP, profile.default(), 3, NIGHTS)
    spike = next((a for a in anomalies if a.kind == "spike"), None)
    if spike is not None:
        inside = [i for i in incidents if spike.start <= i.occurred_at < spike.end]
        assert sum(i.zone_id == spike.zone_id for i in inside) >= len(inside) / 2
    with pytest.raises(ValueError, match="sensitive"):
        profile.Profile(
            profile.DEFAULT_HOURS,
            profile.DEFAULT_WEEKDAYS,
            profile.DEFAULT_MONTHS,
            {"RAPE": 1},
            profile.DEFAULT_LOCATIONS,
            10,
        )
    with pytest.raises(ValueError, match="date range"):
        generate.generate(
            Gap("x", "r", Segment("bpd_calls_for_service", None, None, ("lat",)), "c"),
            profile.default(),
            1,
        )


def test_store_round_trip_and_write_once(tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    incidents, anomalies = generate.generate(GAP, profile.default(), 1, NIGHTS)
    patch = store.write(
        lake, tmp_path / "work", "test_gap", 1, "r1", incidents, anomalies, profile.default()
    )
    assert (patch.incidents, patch.anomalies, patch.profile_origin) == (
        len(incidents),
        len(anomalies),
        "default",
    )
    assert store.patches(lake) == [patch]
    with pytest.raises(FileExistsError):
        store.write(
            lake, tmp_path / "work", "test_gap", 1, "r2", incidents, anomalies, profile.default()
        )
    staged = store.stage(lake, tmp_path / "staging")
    assert sorted(key for key, _ in staged) == [
        "synthetic/test_gap/seed=1/anomalies.parquet",
        "synthetic/test_gap/seed=1/incidents.parquet",
    ]
    with duckdb.connect() as con:
        (n,) = con.execute(
            "SELECT count(*) FROM read_parquet($p)",
            {"p": str(tmp_path / "staging" / "synthetic_incidents" / "test_gap_1.parquet")},
        ).fetchone() or (0,)
    assert n == len(incidents)


def test_news_eval_set_pairs_truth_and_labels_attacks() -> None:
    incidents, _ = generate.generate(GAP, profile.default(), 2, NIGHTS)
    items = news.build(incidents, 2, 50)
    assert len(items) == 50
    adversarial = [e for e in items if e.owasp_id]
    assert 1 <= len(adversarial) <= 12
    assert {e.owasp_id for e in adversarial} <= {"LLM01", "LLM02", "LLM05", "LLM09"}
    assert all(e.truth["incident_type"] in news_types() for e in items)
    report = news.attack_report(RulesExtractor(), items)
    assert report.adversarial == len(adversarial)
    assert report.hijacked <= report.adversarial
    clean = next(e for e in items if e.owasp_id is None)
    got = RulesExtractor().extract(clean.item.text, clean.item.published_at)
    assert got is not None and got.incident_type == clean.truth["incident_type"]


def news_types() -> set[str]:
    return {kind for _, kind in news.WORDING.values()} | {news.DEFAULT_WORDING[1]}


def test_traces_cross_the_zone_with_expected_bands(tmp_path: Path) -> None:
    zone = traces.Zone(39.1666, -86.5290, 100.0)
    rows = traces.walk(4, 2, zone, datetime(2026, 1, 1, 22), steps=120)
    bands = [str(r[9]) for r in rows]
    assert {"inside", "nearby", "away"} <= set(bands)
    assert bands[0] == "away" and "inside" in bands
    assert traces.band(50, zone) == "inside" and traces.band(250, zone) == "nearby"
    assert traces.band(400, zone) == "away"
    traces.save(rows, tmp_path / "t.parquet")
    assert (tmp_path / "t.parquet").exists()


def test_cli_generate_and_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lake = FileLake(tmp_path / "lake")
    monkeypatch.setenv("LAKE_URI", lake.uri)
    caplog.set_level(logging.INFO)
    out = ["--out", str(tmp_path / "out"), "--warehouse", str(tmp_path / "none.duckdb")]
    assert main([*out, "--seed", "3", "generate", "iu_log_2014"]) == 0
    assert "iu_log_2014 seed 3:" in caplog.text and "profile default" in caplog.text
    assert main([*out, "--seed", "3", "generate", "iu_log_2014"]) == 1  # write once
    assert main([*out, "generate", "nope"]) == 1
    assert main([*out, "generate", "bpd_calls_zone_only"]) == 1  # field-level gap
    assert main([*out, "--seed", "3", "news-eval", "iu_log_2014", "--size", "20"]) == 0
    assert "20 items" in caplog.text and "rules:" in caplog.text and "resisted" in caplog.text
    assert (tmp_path / "out" / "news_eval" / "seed=3.jsonl").exists()
    assert main([*out, "--seed", "3", "traces", "--walkers", "1"]) == 0
    assert (tmp_path / "out" / "traces" / "seed=3.parquet").exists()
