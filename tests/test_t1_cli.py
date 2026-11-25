"""t1 CLI: table from a warehouse, rule-only forecast, logs with counts only. Made-up calls."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from campus_safety.t1 import cli

FORECAST = ["zonecode", "night", "window", "expected", "level", "method", "reason"]


def warehouse(path: Path) -> Path:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA silver")
        con.execute(
            "CREATE TABLE silver.bpd_calls_for_service (case_number VARCHAR, called_at TIMESTAMP,"
            " nature VARCHAR, district VARCHAR)"
        )
        start = datetime(2023, 6, 1, 23, 0)
        con.executemany(
            "INSERT INTO silver.bpd_calls_for_service VALUES (?, ?, 'THEFT', ?)",
            [
                (f"c{i}{z}", start + timedelta(days=i), z)
                for i in range(0, 900, 2)
                for z in ("LB1", "LB2")
            ],
        )
    return path


def test_table_then_rule_writes_a_forecast_and_scorecard(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    table = tmp_path / "t1" / "train.parquet"
    assert (
        cli.main(
            ["table", "--warehouse", str(warehouse(tmp_path / "w.duckdb")), "--out", str(table)]
        )
        == 0
    )
    out = tmp_path / "rule"
    assert cli.main(["rule", "--table", str(table), "--out", str(out), "--run-id", "r1"]) == 0
    card = json.loads((out / "scorecard.json").read_text())
    assert (card["method"], card["model"], card["run_id"]) == ("rule", None, "r1")
    found = duckdb.execute("SELECT * FROM read_parquet(?)", [str(out / "forecast.parquet")])
    assert [c[0] for c in found.description] == FORECAST
    rows = found.fetchall()
    assert len(rows) == 2 * 7 and {r[5] for r in rows} == {"rule"}
    assert "THEFT" not in caplog.text and "c0LB1" not in caplog.text  # counts only in logs


def test_missing_table_is_a_clear_error(tmp_path: Path) -> None:
    assert (
        cli.main(["rule", "--table", str(tmp_path / "none.parquet"), "--out", str(tmp_path)]) == 1
    )
