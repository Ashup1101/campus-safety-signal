"""The daily capture Lambda with a fake network: crime log + collectors into bronze, the
12-hour guard, and failures surfacing as errors. All content is made up."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from crime_log_html import incident, page, section

from campus_safety import fetch
from campus_safety.collectors.sources import SOURCES
from campus_safety.iu_crime_log import cli as crime_log
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.lambdas import daily_ingest

LOG = page(section("Bloomington", incident(case="900001", offense="BATTERY NO INJURY"))).encode()


class FakeWeb:
    def __init__(self) -> None:
        self.bodies = {
            s.url: b"<rss><channel><item><title>a</title></item></channel></rss>" for s in SOURCES
        }
        self.bodies[crime_log.URL] = LOG
        self.down: set[str] = set()
        self.clock = datetime.now(UTC)  # the 12-hour guard compares against the real clock

    def get(self, url: str, **kwargs: object) -> fetch.Page:
        if url in self.down:
            raise fetch.HTTPStatusError(url, 503)
        self.clock += timedelta(seconds=5)
        return fetch.Page(url, self.bodies[url], self.clock)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeWeb:
    fake = FakeWeb()
    monkeypatch.setattr(fetch, "polite_get", fake.get)
    monkeypatch.setattr(daily_ingest, "SCRATCH", tmp_path / "scratch")
    # The handler sets RUN_ID for the process (as Lambda would); restore it after each test.
    monkeypatch.setenv("RUN_ID", "test")
    monkeypatch.setattr("campus_safety.collectors.poll.time.sleep", lambda _: None)
    return fake


def context(request: str = "abc-123") -> SimpleNamespace:
    return SimpleNamespace(aws_request_id=request)


def test_captures_the_crime_log_and_polls_every_source(web: FakeWeb, tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    summary = daily_ingest.handler({}, context(), lake)
    assert summary == {"crime_log": "ok", "stored": len(SOURCES), "unchanged": 0, "failed": {}}
    (snapshot,) = bronze.manifests(lake, "iu_crime_log")
    assert snapshot.run_id == "lambda-abc-123"
    assert all(len(bronze.manifests(lake, s.name)) == 1 for s in SOURCES)


def test_twelve_hour_guard_and_unchanged_sources(web: FakeWeb, tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    daily_ingest.handler({}, context("first"), lake)
    again = daily_ingest.handler({}, context("second"), lake)
    assert again == {"crime_log": "ok", "stored": 0, "unchanged": len(SOURCES), "failed": {}}
    assert len(bronze.manifests(lake, "iu_crime_log")) == 1


def test_a_failed_crime_log_still_polls_then_raises(web: FakeWeb, tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    web.down.add(crime_log.URL)
    web.down.add(SOURCES[0].url)
    with pytest.raises(daily_ingest.CaptureError, match="HTTPStatusError"):
        daily_ingest.handler({}, context(), lake)
    assert bronze.manifests(lake, "iu_crime_log") == []
    assert len(bronze.manifests(lake, SOURCES[1].name)) == 1
    assert bronze.manifests(lake, SOURCES[0].name) == []


def test_run_id_is_bounded_and_valid() -> None:
    assert (
        daily_ingest.run_id(SimpleNamespace(aws_request_id="x" * 100))
        == ("lambda-" + "x" * 100)[:64]
    )
    assert daily_ingest.run_id(object()) == "lambda-manual"


def test_the_package_imports_without_install_metadata() -> None:
    """Lambda runs src/ as plain files with no install metadata: the version must fall back."""
    import subprocess
    import sys

    code = (
        "import importlib.metadata as m\n"
        "real = m.version\n"
        "def version(name):\n"
        "    if name == 'campus-safety-signal': raise m.PackageNotFoundError(name)\n"
        "    return real(name)\n"
        "m.version = version\n"
        "import campus_safety.lambdas.daily_ingest, campus_safety.lambdas.alert_fanout\n"
        "from campus_safety.fetch import USER_AGENT\n"
        "print(USER_AGENT)\n"
    )
    out = subprocess.run(  # noqa: S603 (fixed interpreter and code)
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.startswith("campus-safety-signal/0.1.0 ")
