"""AUTH_MODE=supabase: verified sessions map to accounts by email; a new email chooses a role."""

from pathlib import Path

from supabase_fakes import bearer, session_token, supabase_client


def test_a_new_email_chooses_a_role_once_then_uses_the_app(tmp_path: Path) -> None:
    app, client = supabase_client(tmp_path)
    pat = bearer("Pat@Example.test")
    assert client.get("/api/session", headers=pat).json() == {"state": "choose_role"}
    assert client.get("/api/links", headers=pat).status_code == 409  # choose a role first
    made = client.post("/api/me/role", headers=pat, json={"role": "parent", "display_name": "Pat"})
    assert made.status_code == 201 and made.json()["role"] == "parent"
    again = client.post("/api/me/role", headers=pat, json={"role": "student", "display_name": "P"})
    assert again.status_code == 409
    state = client.get("/api/session", headers=pat).json()
    assert state["state"] == "active" and state["account"]["role"] == "parent"
    assert client.get("/api/links", headers=pat).status_code == 200
    store = app.state.store
    account = store.account_by_email("pat@example.test")
    assert account.self_service and store.auth_user(account.id) == "user-Pat@Example.test"


def test_the_console_role_cannot_be_chosen(tmp_path: Path) -> None:
    _, client = supabase_client(tmp_path)
    body = {"role": "console", "display_name": "Me"}
    assert (
        client.post("/api/me/role", headers=bearer("x@example.test"), json=body).status_code == 422
    )


def test_bad_or_missing_sessions_get_401(tmp_path: Path) -> None:
    _, client = supabase_client(tmp_path)
    expired = {"Authorization": f"Bearer {session_token('a@example.test', exp=1)}"}
    for headers in ({}, expired, {"Authorization": "Bearer nonsense"}):
        assert client.get("/api/session", headers=headers).status_code == 401
        assert client.get("/api/links", headers=headers).status_code == 401
        assert (
            client.post(
                "/api/me/role", headers=headers, json={"role": "parent", "display_name": "A"}
            ).status_code
            == 401
        )


def test_another_auth_user_with_the_same_email_is_refused(tmp_path: Path) -> None:
    _, client = supabase_client(tmp_path)
    first = bearer("kim@example.test", "user-1")
    client.post("/api/me/role", headers=first, json={"role": "student", "display_name": "Kim"})
    assert client.get("/api/links", headers=first).status_code == 200
    assert client.get("/api/links", headers=bearer("kim@example.test", "user-2")).status_code == 401


def test_demo_sign_in_routes_are_off_in_supabase_mode(tmp_path: Path) -> None:
    _, client = supabase_client(tmp_path)
    assert client.get("/api/accounts").status_code == 403
    assert client.post("/api/login", json={"account_id": "student_sam"}).status_code == 403
    assert client.post("/api/signin", json={"email": "a@example.test"}).status_code == 403
    signup = {"email": "a@example.test", "role": "parent", "display_name": "A"}
    assert client.post("/api/signup", json=signup).status_code == 403
    assert client.get("/api/magic/whatever").status_code == 403


def test_the_websocket_accepts_a_verified_session_only(tmp_path: Path) -> None:
    _, client = supabase_client(tmp_path)
    pat = bearer("pat@example.test")
    client.post("/api/me/role", headers=pat, json={"role": "parent", "display_name": "Pat"})
    token = pat["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(f"/ws?token={token}") as ws:
        assert ws is not None
