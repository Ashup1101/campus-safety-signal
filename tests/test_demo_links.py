"""Parent-student linking only with the student's OK. Made-up accounts."""

from pathlib import Path

from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings


def signed_in(
    client: TestClient, app_store: object, email: str, role: str, name: str
) -> dict[str, str]:
    from test_demo_auth import link_in_mailbox

    client.post("/api/signup", json={"email": email, "role": role, "display_name": name})
    account = app_store.account_by_email(email)  # type: ignore[attr-defined]
    token = link_in_mailbox(app_store, account.id)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {client.get(f'/api/magic/{token}').json()['token']}"}


def app_and_client(tmp_path: Path) -> tuple[object, TestClient]:
    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    return app, TestClient(app)


def test_a_parent_invites_a_student_by_email_once(tmp_path: Path) -> None:
    app, client = app_and_client(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    parent = signed_in(client, store, "pat@example.test", "parent", "Pat")
    student = signed_in(client, store, "kim@example.test", "student", "Kim")
    sent = client.post("/api/invites", headers=parent, json={"student_email": "KIM@example.test"})
    assert sent.status_code == 201
    again = client.post("/api/invites", headers=parent, json={"student_email": "kim@example.test"})
    assert again.status_code == 409
    assert (
        client.post(
            "/api/invites", headers=student, json={"student_email": "x@example.test"}
        ).status_code
        == 403
    )
    pending = client.get("/api/invites", headers=student).json()
    assert [(i["from"], i["status"]) for i in pending] == [("Pat", "pending")]
    assert [i["status"] for i in client.get("/api/invites", headers=parent).json()] == ["pending"]
