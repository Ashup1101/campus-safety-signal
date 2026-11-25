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
    settings = Settings(data_dir=tmp_path / "d", warehouse=db, tiles=tmp_path / "t")
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
