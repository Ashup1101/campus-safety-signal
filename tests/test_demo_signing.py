"""Demo signing keys for band answers: one per linked student device, created at link time, sent
once over the student's own authenticated socket, rotated on relink. Made-up accounts."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings
from demo_server.store import Store


def app_for(tmp_path: Path) -> tuple[Store, TestClient]:
    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    return app.state.store, TestClient(app)


def token(client: TestClient, account_id: str) -> str:
    return str(client.post("/api/login", json={"account_id": account_id}).json()["token"])


def test_a_link_provisions_a_key_that_reaches_the_student_once(tmp_path: Path) -> None:
    store, client = app_for(tmp_path)
    key = store.device_key("student_sam")  # seeded link Mom -> Sam
    assert key is not None and len(key[1]) == 64
    with client.websocket_connect(f"/ws?token={token(client, 'student_sam')}") as ws:
        hello = ws.receive_json()
    assert hello["signing"] == {"key_id": key[0], "secret": key[1], "label": "demo signing"}
    with client.websocket_connect(f"/ws?token={token(client, 'student_sam')}") as ws:
        assert "signing" not in ws.receive_json()  # sent once
    with client.websocket_connect(f"/ws?token={token(client, 'parent_mom')}") as ws:
        assert "signing" not in ws.receive_json()  # never to a parent


def test_relinking_rotates_the_key_and_delete_removes_it(tmp_path: Path) -> None:
    store, _ = app_for(tmp_path)
    first = store.device_key("student_sam")
    store.unlink("parent_mom", "student_sam")
    store.link("parent_mom", "student_sam", "Mom")
    second = store.device_key("student_sam")
    assert first and second and first[0] != second[0] and first[1] != second[1]
    sam = store.account("student_sam")
    assert sam is not None
    store.delete_account(sam)
    assert store.device_key("student_sam") is None


def test_provisioning_stamps_the_time(tmp_path: Path) -> None:
    store, _ = app_for(tmp_path)
    at = datetime(2026, 11, 26, tzinfo=UTC)
    key_id, _secret = store.provision_key("student_alex", at)
    assert store.device_key("student_alex") == (key_id, _secret)
