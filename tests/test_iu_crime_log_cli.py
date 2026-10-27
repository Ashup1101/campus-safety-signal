import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from crime_log_html import NO_CRIMES, incident, page, section

from campus_safety import fetch
from campus_safety.iu_crime_log.cli import LEGACY_SNAPSHOTS, main
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake

GOOD = page(section("Bloomington", incident(case="900001") + incident(case="900002")))


@pytest.fixture
def lake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FileLake:
    monkeypatch.setenv("LAKE_URI", (tmp_path / "lake").as_uri())
    monkeypatch.delenv("RUN_ID", raising=False)
    return FileLake(tmp_path / "lake")


def serve(monkeypatch: pytest.MonkeyPatch, html: str, age: timedelta = timedelta()) -> list[str]:
    requested: list[str] = []

    def fake_polite_get(url: str) -> fetch.Page:
        requested.append(url)
        return fetch.Page(url, html.encode(), datetime.now(UTC) - age)

    monkeypatch.setattr(fetch, "polite_get", fake_polite_get)
    return requested


def run(tmp_path: Path, *args: str) -> int:
    return main(["--data-dir", str(tmp_path / "data"), *args])


def test_run_writes_bronze_then_validates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lake: FileLake
) -> None:
    serve(monkeypatch, GOOD)
    assert run(tmp_path, "run") == 0
    (manifest,) = bronze.manifests(lake, "iu_crime_log")
    assert bronze.read(lake, manifest) == GOOD.encode()
    assert manifest.http_status == 200
    assert manifest.run_id.startswith("local-")


def test_run_takes_the_run_id_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lake: FileLake
) -> None:
    monkeypatch.setenv("RUN_ID", "gha-7-1")
    serve(monkeypatch, GOOD)
    run(tmp_path, "run")
    assert [m.run_id for m in bronze.manifests(lake, "iu_crime_log")] == ["gha-7-1"]


def test_run_skips_when_bronze_is_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lake: FileLake
) -> None:
    requested = serve(monkeypatch, GOOD)
    run(tmp_path, "run")
    run(tmp_path, "run")
    assert len(requested) == 1


def test_run_fetches_again_once_bronze_is_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lake: FileLake
) -> None:
    serve(monkeypatch, GOOD, age=timedelta(hours=13))
    run(tmp_path, "run")
    requested = serve(monkeypatch, GOOD)
    run(tmp_path, "run")
    assert len(requested) == 1
    assert len(bronze.manifests(lake, "iu_crime_log")) == 2


def test_zero_interval_never_lists_bronze(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lake: FileLake
) -> None:
    # The CI role may only PutObject, so a listing would be denied.
    def no_listing(*args: object) -> None:
        raise AssertionError("listed bronze")

    monkeypatch.setattr(bronze, "latest_fetch", no_listing)
    serve(monkeypatch, GOOD)
    assert run(tmp_path, "run", "--min-interval-hours", "0") == 0


@pytest.mark.parametrize(
    "html", ["<html>redesigned</html>", page(section("Bloomington", NO_CRIMES))]
)
def test_failed_validation_keeps_the_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lake: FileLake, html: str
) -> None:
    serve(monkeypatch, html)
    assert run(tmp_path, "run") == 1
    assert len(bronze.manifests(lake, "iu_crime_log")) == 1


def test_run_needs_a_lake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LAKE_URI", raising=False)
    requested = serve(monkeypatch, GOOD)
    assert run(tmp_path, "run") == 1
    assert requested == []


def test_check_stores_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LAKE_URI", raising=False)
    serve(monkeypatch, GOOD)
    assert run(tmp_path, "check") == 0
    assert list(tmp_path.iterdir()) == []


def test_check_fails_on_zero_incidents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    serve(monkeypatch, page(section("Bloomington", NO_CRIMES)))
    assert run(tmp_path, "check") == 1


def test_import_keeps_fetch_times_and_is_rerunnable(tmp_path: Path, lake: FileLake) -> None:
    legacy = tmp_path / "data" / LEGACY_SNAPSHOTS / "2026"
    legacy.mkdir(parents=True)
    (legacy / "20261026T204623Z.html.gz").write_bytes(gzip.compress(GOOD.encode()))
    assert run(tmp_path, "import-snapshots") == 0
    assert run(tmp_path, "import-snapshots") == 0
    (manifest,) = bronze.manifests(lake, "iu_crime_log")
    assert manifest.fetched_at == datetime(2026, 10, 26, 20, 46, 23, tzinfo=UTC)
    assert manifest.run_id.startswith("import-")
    assert bronze.read(lake, manifest) == GOOD.encode()
