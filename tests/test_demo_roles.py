"""Students, parents and the IUPD console are kept apart: each role gets only its own routes."""

from pathlib import Path

import pytest
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
