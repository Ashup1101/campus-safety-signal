"""Students, parents and the IUPD console are kept apart: each role gets only its own routes."""

from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings

CONSOLE_ONLY: list[tuple[str, str, dict[str, str] | None]] = [
    ("get", "/api/watcher", None),
    ("get", "/api/tonight-model", None),
    ("get", "/api/replays", None),
    ("get", "/api/latency", None),
    ("post", "/api/drill", {"action": "drill"}),
    ("post", "/api/clock", {"preset": "live"}),
]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t"
    )
    return TestClient(create_app(settings))


def headers(client: TestClient, account_id: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": account_id}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("account_id", ["student_sam", "parent_mom"])
def test_students_and_parents_never_reach_the_console(client: TestClient, account_id: str) -> None:
    me = headers(client, account_id)
    for method, path, body in CONSOLE_ONLY:
        answer = (
            client.post(path, headers=me, json=body)
            if method == "post"
            else client.get(path, headers=me)
        )
        assert answer.status_code == 403, path


def test_only_parents_invite_and_only_the_invited_student_answers(client: TestClient) -> None:
    sam, mom = headers(client, "student_sam"), headers(client, "parent_mom")
    assert (
        client.post("/api/invites", headers=sam, json={"student_email": "a@b.test"}).status_code
        == 403
    )
    assert client.post("/api/invites/1/accept", headers=mom).status_code == 404


@pytest.mark.parametrize("account_id", ["student_sam", "parent_mom", None])
def test_every_console_api_route_refuses_families_and_strangers(
    tmp_path: Path, account_id: str | None
) -> None:
    """Walks the app's own route table, so a console route added later is covered too."""
    settings = Settings(
        data_dir=tmp_path / "d",
        warehouse=tmp_path / "n.duckdb",
        tiles=tmp_path / "t",
        lake_uri=(tmp_path / "lake").as_uri(),
    )
    app = create_app(settings)
    client = TestClient(app)
    me = headers(client, account_id) if account_id else {}
    paths = sorted(
        r.path
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path.startswith("/api/console/")
        and "GET" in (r.methods or ())
    )
    assert (
        len(paths) >= 8
    )  # gaps, cross-check, archive, alert-metrics, health, forecasts, zones, trends
    for path in paths:
        assert client.get(path, headers=me).status_code in ((403,) if account_id else (401, 403)), (
            path
        )
