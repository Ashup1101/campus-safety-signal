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


def test_the_student_decides_and_either_side_can_unlink(tmp_path: Path) -> None:
    app, client = app_and_client(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    parent = signed_in(client, store, "pat@example.test", "parent", "Pat")
    student = signed_in(client, store, "kim@example.test", "student", "Kim")
    other = signed_in(client, store, "lee@example.test", "student", "Lee")
    pat, kim = (
        store.account_by_email("pat@example.test"),
        store.account_by_email("kim@example.test"),
    )
    invite = client.post(
        "/api/invites", headers=parent, json={"student_email": "kim@example.test"}
    ).json()
    assert client.post(f"/api/invites/{invite['id']}/accept", headers=other).status_code == 404
    assert client.post(f"/api/invites/{invite['id']}/accept", headers=parent).status_code == 404
    assert store.students_of(pat.id) == []  # nothing until the student says yes
    assert client.post(f"/api/invites/{invite['id']}/accept", headers=student).status_code == 200
    assert store.students_of(pat.id) == [kim.id]
    assert (
        client.post(f"/api/invites/{invite['id']}/accept", headers=student).status_code == 404
    )  # done
    assert client.delete(f"/api/links/{pat.id}", headers=student).status_code == 204
    assert store.students_of(pat.id) == []
    notice = store.mailbox(pat.id)[0]
    assert (notice["kind"], notice["subject"]) == ("account", "Kim unlinked")
    second = client.post(
        "/api/invites", headers=parent, json={"student_email": "kim@example.test"}
    ).json()
    assert client.post(f"/api/invites/{second['id']}/decline", headers=student).status_code == 200
    assert store.students_of(pat.id) == []
    assert client.delete(f"/api/links/{pat.id}", headers=student).status_code == 404  # no link


def test_the_student_sees_the_relationship_the_parent_chose(tmp_path: Path) -> None:
    app, client = app_and_client(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    cases = [
        ("mother", "Mom"),
        ("guardian", "Guardian"),
        ("Aunt Maria", "Aunt Maria"),
        (None, "Pat3"),
    ]
    for n, (relationship, label) in enumerate(cases):
        parent = signed_in(client, store, f"pat{n}@example.test", "parent", f"Pat{n}")
        student = signed_in(client, store, f"kim{n}@example.test", "student", f"Kim{n}")
        body = {"student_email": f"kim{n}@example.test"}
        if relationship:
            body["relationship"] = relationship
        invite = client.post("/api/invites", headers=parent, json=body).json()
        client.post(f"/api/invites/{invite['id']}/accept", headers=student)
        kim = store.account_by_email(f"kim{n}@example.test")
        assert list(store.parents_of(kim.id).values()) == [label]
    parent = signed_in(client, store, "x@example.test", "parent", "X")
    for bad in ("call 555 1234", "https://x.test", "a" * 31, " "):
        body = {"student_email": "kim0@example.test", "relationship": bad}
        assert client.post("/api/invites", headers=parent, json=body).status_code == 400
