"""IUPD console API: console role only; real-only by default. Made-up gap rows."""

from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings


def client_for(tmp_path: Path, with_gaps: bool = True) -> TestClient:
    db = tmp_path / "w.duckdb"
    if with_gaps:
        with duckdb.connect(str(db)) as con:
            con.execute("CREATE SCHEMA gold")
            con.execute(
                "CREATE TABLE gold.gap_report AS SELECT 'iu_log_2014' AS gap_id,"
                " 'iu_crime_log' AS source, DATE '2014-01-02' AS span_start,"
                " DATE '2014-12-31' AS span_end, 364 AS span_days, 'all' AS fields,"
                " 1 AS real_days_covered, 3 AS real_incidents, 848 AS synthetic_rows,"
                " 1 AS synthetic_seeds, 2 AS planted_anomalies, 40 AS clery_total,"
                " 'IUPD daily logs' AS closing_source"
            )
            con.execute(
                "CREATE TABLE gold.console_cross_check AS SELECT DATE '2026-10-01' AS month,"
                " 'LB101' AS zonecode, 'theft' AS category, 1 AS iu_count, 2 AS bpd_count"
            )
            con.execute(
                "CREATE TABLE gold.tonight AS SELECT zone AS zonecode, night::DATE AS night,"
                " w AS \"window\", 1.5::DOUBLE AS expected, 'quiet' AS level, 'rule' AS method,"
                " 'About a usual night here' AS reason, 'gh-1' AS run_id"
                " FROM (VALUES ('LB101'), ('LB102')) AS z(zone),"
                " range(DATE '2026-10-29', DATE '2026-11-06', INTERVAL 1 DAY) AS n(night),"
                " (VALUES ('late_night'), ('evening')) AS v(w)"
            )
            con.execute(
                "CREATE TABLE gold.archive_coverage AS SELECT * FROM (VALUES"
                " (2017, 3, 1, 1, 1), (2025, 1, 1, 0, 0))"
                " AS t(year, listed, parsed, failed, not_fetched)"
            )
            con.execute(
                "CREATE TABLE gold.calibration_bpd_cfs_check AS SELECT 2026 AS period_year,"
                " 9 AS period_month, 1000 AS reported_calls, 990 AS feed_calls,"
                " -10 AS difference, -1.0::DOUBLE AS pct_difference"
            )
    settings = Settings(
        data_dir=tmp_path / "d",
        warehouse=db,
        tiles=tmp_path / "t",
        lake_uri=(tmp_path / "lake").as_uri(),
    )
    return TestClient(create_app(settings))


def login(client: TestClient, account_id: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": account_id}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_gaps_are_console_only_and_real_only_by_default(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert client.get("/api/console/gaps", headers=login(client, "parent_mom")).status_code == 403
    console = login(client, "console")
    real = client.get("/api/console/gaps", headers=console).json()
    assert real[0]["gap_id"] == "iu_log_2014" and real[0]["reason"]
    assert "synthetic_rows" not in real[0]  # nothing synthetic unless asked
    mixed = client.get("/api/console/gaps?real_only=false", headers=console).json()
    assert mixed[0]["synthetic_rows"] == 848


def test_gaps_without_a_warehouse_are_empty(tmp_path: Path) -> None:
    client = client_for(tmp_path, with_gaps=False)
    assert client.get("/api/console/gaps", headers=login(client, "console")).json() == []


def test_cross_check_says_calls_are_not_crimes(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    url = "/api/console/cross-check"
    assert client.get(url, headers=login(client, "student_sam")).status_code == 403
    body = client.get(url, headers=login(client, "console")).json()
    assert "not crimes" in body["note"]
    assert body["rows"] == [
        {"month": "2026-10-01", "zonecode": "LB101", "category": "theft", "iu_count": 1,
         "bpd_count": 2}
    ]  # fmt: skip
    assert body["calibration"][0]["pct_difference"] == -1.0
    empty = client_for(tmp_path / "none", with_gaps=False)
    assert empty.get(url, headers=login(empty, "console")).json()["rows"] == []


def test_archive_coverage_per_year(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    url = "/api/console/archive"
    assert client.get(url, headers=login(client, "parent_mom")).status_code == 403
    assert client.get(url, headers=login(client, "console")).json() == [
        {"year": 2017, "listed": 3, "parsed": 1, "failed": 1, "not_fetched": 1},
        {"year": 2025, "listed": 1, "parsed": 1, "failed": 0, "not_fetched": 0},
    ]


def test_alert_metrics_are_console_only_with_a_bounded_period(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    url = "/api/console/alert-metrics"
    assert client.get(url, headers=login(client, "student_sam")).status_code == 403
    console = login(client, "console")
    body = client.get(f"{url}?days=7", headers=console).json()
    assert body["days"] == 7 and set(body["latency"]) == {"web", "ios"}
    assert client.get(f"{url}?days=0", headers=console).status_code == 422


def test_health_lists_every_configured_source(tmp_path: Path) -> None:
    from campus_safety.lake import health

    client = client_for(tmp_path)
    url = "/api/console/health"
    assert client.get(url, headers=login(client, "parent_mom")).status_code == 403
    found = client.get(url, headers=login(client, "console")).json()
    assert [row["source"] for row in found] == [c.source for c in health.load()]
    assert {row["state"] for row in found} == {"never"}  # an empty lake
    assert {"label", "expected_hours", "last_stored_at", "error_kind"} <= set(found[0])


def test_forecasts_name_the_method_and_mark_event_nights(tmp_path: Path) -> None:
    from test_t1_import import run_dir

    from campus_safety.lake.storage import FileLake
    from campus_safety.t1 import importer

    client = client_for(tmp_path)
    importer.import_run(FileLake(tmp_path / "lake"), run_dir(tmp_path / "run"))
    url = "/api/console/forecasts"
    assert client.get(url, headers=login(client, "student_sam")).status_code == 403
    body = client.get(url, headers=login(client, "console")).json()
    assert body["method_words"] == "simple rule" and "not crimes" in body["note"]
    nights = body["outlook"]["nights"]
    assert [n["night"] for n in nights][:2] == ["2026-10-29", "2026-10-30"] and len(nights) == 7
    assert nights[1]["event"] == "Halloween weekend" and nights[0]["event"] is None
    assert nights[0]["campus_expected"] == 3.0  # two zones, late night only
    assert [z["zonecode"] for z in body["outlook"]["zones"]] == ["LB101", "LB102"]
    assert body["scorecard"]["method"] == "rule" and body["scorecard"]["scores"]["rule"]
    assert body["tonight"] == {"night": None, "zones": []}  # the run does not cover today


def test_forecasts_without_a_run_are_empty_not_invented(tmp_path: Path) -> None:
    client = client_for(tmp_path, with_gaps=False)
    body = client.get("/api/console/forecasts", headers=login(client, "console")).json()
    assert body["method"] is None and body["scorecard"] is None
    assert body["outlook"] == {"nights": [], "zones": []}


def test_tonight_lists_each_zone_when_the_run_covers_it() -> None:
    from datetime import date

    from demo_server import forecasts

    rows = [
        {"zonecode": z, "night": date(2026, 10, 30), "expected": 2.0, "level": "elevated",
         "method": "model", "reason": "Busier than usual", "run_id": "gh-2"}
        for z in ("LB101", "LB102")
    ]  # fmt: skip
    found = forecasts.build(rows, None, [], date(2026, 10, 30))
    assert found["tonight"]["night"] == date(2026, 10, 30)
    assert [z["zonecode"] for z in found["tonight"]["zones"]] == ["LB101", "LB102"]
    assert found["method_words"] == "forecast model"
