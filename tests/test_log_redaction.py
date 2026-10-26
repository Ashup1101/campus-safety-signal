"""Record contents never reach logs or error text, even when parsing fails mid-record."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from crime_log_html import incident, page, section

from campus_safety import fetch
from campus_safety.iu_crime_log import store
from campus_safety.iu_crime_log.cli import UNCLASSIFIED_FILE, main
from campus_safety.iu_crime_log.parse import ParseError, parse_crime_log

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


def serve(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
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
    serve(monkeypatch, html)
    assert main(["--data-dir", str(tmp_path), command]) == 1
    out, err = capsys.readouterr()
    assert MARK not in caplog.text + out + err


def test_rebuild_skip_warning_has_no_record_contents(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store.write_snapshot(
        tmp_path, BROKEN_PAGES["bad date"].encode(), datetime(2026, 10, 25, tzinfo=UTC)
    )
    assert main(["--data-dir", str(tmp_path), "rebuild"]) == 1
    assert "skip" in caplog.text
    assert MARK not in caplog.text


def test_unclassified_labels_go_to_a_local_file_not_the_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    label = f"UNHEARD OF OFFENSE {MARK}"
    serve(monkeypatch, page(section("Bloomington", incident(offense=label))))
    assert main(["--data-dir", str(tmp_path), "run"]) == 0
    assert "1 unclassified offense labels" in caplog.text
    assert MARK not in caplog.text
    assert (tmp_path / UNCLASSIFIED_FILE).read_text() == f"{label}\n"


def test_check_reports_unclassified_count_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    serve(monkeypatch, page(section("Bloomington", incident(offense=f"UNHEARD {MARK}"))))
    assert main(["--data-dir", str(tmp_path / "data"), "check"]) == 0
    assert "1 unclassified offense labels" in caplog.text
    assert MARK not in caplog.text
    assert not (tmp_path / "data").exists()
