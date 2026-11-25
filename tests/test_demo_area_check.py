"""Check my area: nearby levels from one location reading that is never stored or logged."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings

HERE = {"lat": 39.16655, "lon": -86.5290}  # inside the hand-drawn Kirkwood 400 block


def test_nearby_levels_and_nothing_kept(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    settings = Settings(
        data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t"
    )
    client = TestClient(create_app(settings))
    token = client.post("/api/login", json={"account_id": "student_sam"}).json()["token"]
    me = {"Authorization": f"Bearer {token}"}
    found = client.post("/api/area-check", headers=me, json=HERE)
    assert found.status_code == 200
    nearby = found.json()["segments"]
    assert nearby[0]["id"] == "kirkwood_400" and nearby[0]["meters"] < 50
    assert all(s["meters"] <= 400 for s in nearby) and "late_night" in nearby[0]["levels"]
    assert "39.16655" not in caplog.text and "-86.529" not in caplog.text
    assert b"39.16655" not in (tmp_path / "d" / "demo.sqlite3").read_bytes()
    assert (
        client.post("/api/area-check", headers=me, json={"lat": 40.5, "lon": -86.5}).status_code
        == 422
    )
    assert client.post("/api/area-check", json=HERE).status_code == 401
