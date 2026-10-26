import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from crime_log_html import NO_CRIMES, incident, page, section

from campus_safety import fetch
from campus_safety.iu_crime_log import store
from campus_safety.iu_crime_log.cli import main

GOOD = page(section("Bloomington", incident(case="900001") + incident(case="900002")))


def serve(monkeypatch: pytest.MonkeyPatch, html: str, age: timedelta = timedelta()) -> list[str]:
    requested: list[str] = []

    def fake_polite_get(url: str) -> fetch.Page:
        requested.append(url)
        return fetch.Page(url, html.encode(), datetime.now(UTC) - age)

    monkeypatch.setattr(fetch, "polite_get", fake_polite_get)
    return requested


def incident_count(data_dir: Path) -> int:
    with closing(sqlite3.connect(data_dir / store.DB_NAME)) as conn:
        (count,) = conn.execute("SELECT count(*) FROM incidents").fetchone()
    return int(count)


def test_run_snapshots_and_stores(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    serve(monkeypatch, GOOD)
    assert main(["--data-dir", str(tmp_path), "run"]) == 0
    (snapshot,) = store.list_snapshots(tmp_path)
    assert store.read_snapshot(snapshot) == GOOD.encode()
    assert incident_count(tmp_path) == 2


def test_run_skips_when_last_snapshot_is_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requested = serve(monkeypatch, GOOD)
    main(["--data-dir", str(tmp_path), "run"])
    main(["--data-dir", str(tmp_path), "run"])
    assert len(requested) == 1


def test_run_fetches_again_once_snapshot_is_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    serve(monkeypatch, GOOD, age=timedelta(hours=13))
    main(["--data-dir", str(tmp_path), "run"])
    requested = serve(monkeypatch, GOOD)
    main(["--data-dir", str(tmp_path), "run"])
    assert len(requested) == 1
    assert len(store.list_snapshots(tmp_path)) == 2


def test_parse_failure_keeps_the_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    serve(monkeypatch, "<html>redesigned</html>")
    assert main(["--data-dir", str(tmp_path), "run"]) == 1
    assert len(store.list_snapshots(tmp_path)) == 1
    assert not (tmp_path / store.DB_NAME).exists()


def test_check_stores_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    serve(monkeypatch, GOOD)
    assert main(["--data-dir", str(tmp_path / "data"), "check"]) == 0
    assert not (tmp_path / "data").exists()


def test_check_fails_on_zero_incidents(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, page(section("Bloomington", NO_CRIMES)))
    assert main(["check"]) == 1


def test_rebuild_replays_snapshots_and_skips_broken_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store.write_snapshot(tmp_path, GOOD.encode(), datetime(2026, 10, 25, tzinfo=UTC))
    store.write_snapshot(tmp_path, b"<html>broken</html>", datetime(2026, 10, 26, tzinfo=UTC))
    assert main(["--data-dir", str(tmp_path), "rebuild"]) == 1
    assert incident_count(tmp_path) == 2
    assert not (tmp_path / f"{store.DB_NAME}.rebuild").exists()
