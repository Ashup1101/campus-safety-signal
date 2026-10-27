"""Record contents never reach logs or error text, even when parsing fails mid-record."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from crime_log_html import incident, page, section

from campus_safety import fetch
from campus_safety.iu_crime_log.cli import UNCLASSIFIED_FILE, main
from campus_safety.iu_crime_log.parse import ParseError, parse_crime_log
from campus_safety.lake import bronze
from campus_safety.lake import cli as lake_cli
from campus_safety.lake.storage import FileLake

MARK = "ZQXJ"
SECRET = {"case": f"{MARK}-1", "location": f"{MARK} HALL", "offense": f"SEXUAL OFFENSE {MARK}"}


def secret_incident(**overrides: str) -> str:
    return incident(**{**SECRET, **overrides})


BROKEN_PAGES = {
    "renamed label": page(section("Bloomington", secret_incident().replace("Crime Desc", "Desc"))),
    "bad date": page(section("Bloomington", secret_incident(reported=f"{MARK}-DATE"))),
    "bad time": page(section("Bloomington", secret_incident(start=f"{MARK}-TIME"))),
    "blank case": page(section("Bloomington", secret_incident(case=""))),
    "differing repeat": page(
        section("Bloomington", secret_incident() + secret_incident(disposition=f"{MARK}-DISP"))
    ),
    "stray row": page(
        section("Bloomington", secret_incident() + f'<tr role="row"><td>{MARK}</td></tr>')
    ),
    "extra cell": page(
        section(
            "Bloomington",
            secret_incident().replace(
                '<td role="presentation"></td>', f"<td>{MARK}</td><td></td>", 1
            ),
        )
    ),
    "bad window": page(section("Bloomington", secret_incident(), window=f"{MARK} - {MARK}")),
}


def serve(monkeypatch: pytest.MonkeyPatch, html: str, lake_dir: Path) -> None:
    monkeypatch.setenv("LAKE_URI", lake_dir.as_uri())

    def fake_polite_get(url: str) -> fetch.Page:
        return fetch.Page(url, html.encode(), datetime.now(UTC))

    monkeypatch.setattr(fetch, "polite_get", fake_polite_get)


@pytest.mark.parametrize("html", BROKEN_PAGES.values(), ids=BROKEN_PAGES.keys())
def test_parse_error_text_has_no_record_contents(html: str) -> None:
    with pytest.raises(ParseError) as error:
        parse_crime_log(html)
    assert MARK not in str(error.value)


@pytest.mark.parametrize("command", ["run", "check"])
@pytest.mark.parametrize("html", BROKEN_PAGES.values(), ids=BROKEN_PAGES.keys())
def test_failed_parse_logs_no_record_contents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    html: str,
    command: str,
) -> None:
    serve(monkeypatch, html, tmp_path / "lake")
    assert main(["--data-dir", str(tmp_path), command]) == 1
    out, err = capsys.readouterr()
    assert MARK not in caplog.text + out + err


def test_transform_logs_no_record_contents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake = FileLake(tmp_path / "lake")
    for day, html in enumerate(BROKEN_PAGES.values()):
        bronze.write(
            lake,
            source="iu_crime_log",
            body=html.encode(),
            url="https://protect.example.edu/log.html",
            fetched_at=datetime(2026, 10, 1 + day, tzinfo=UTC),
            http_status=200,
            run_id=f"r{day}",
            ext="html",
        )
    monkeypatch.setenv("LAKE_URI", lake.uri)
    caplog.set_level(logging.INFO)
    assert lake_cli.main(["--work-dir", str(tmp_path / "work"), "transform"]) == 0
    out, err = capsys.readouterr()
    assert f"{len(BROKEN_PAGES)} failed to parse" in caplog.text
    assert MARK not in caplog.text + out + err


def test_unclassified_labels_go_to_a_local_file_not_the_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    label = f"UNHEARD OF OFFENSE {MARK}"
    serve(monkeypatch, page(section("Bloomington", incident(offense=label))), tmp_path / "lake")
    assert main(["--data-dir", str(tmp_path), "run"]) == 0
    assert "1 unclassified offense labels" in caplog.text
    assert MARK not in caplog.text
    assert (tmp_path / UNCLASSIFIED_FILE).read_text() == f"{label}\n"


def test_check_reports_unclassified_count_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    serve(
        monkeypatch,
        page(section("Bloomington", incident(offense=f"UNHEARD {MARK}"))),
        tmp_path / "lake",
    )
    assert main(["--data-dir", str(tmp_path / "data"), "check"]) == 0
    assert "1 unclassified offense labels" in caplog.text
    assert MARK not in caplog.text
    assert not (tmp_path / "data").exists()
