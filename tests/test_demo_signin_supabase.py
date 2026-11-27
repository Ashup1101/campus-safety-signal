"""AUTH_MODE=supabase: verified sessions map to accounts by email; a new email chooses a role."""

from pathlib import Path
from typing import Any

import pytest
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


def _allow(tmp_path: Path, *emails: str) -> Path:
    path = tmp_path / "allow.yaml"
    path.write_text("emails:\n" + "".join(f"  - {e}\n" for e in emails))
    return path


def test_only_allowlisted_emails_get_the_console(tmp_path: Path) -> None:
    allow = _allow(tmp_path, "Officer@IU-Example.test")
    _, client = supabase_client(tmp_path, console_allowlist=allow)
    officer = bearer("officer@iu-example.test")
    state = client.get("/api/session", headers=officer).json()
    assert state["state"] == "active" and state["account"]["role"] == "console"
    assert client.get("/api/console/database", headers=officer).status_code == 200
    body = {"role": "parent", "display_name": "O"}
    assert client.post("/api/me/role", headers=officer, json=body).status_code == 409
    other = bearer("someone@example.test")
    assert client.get("/api/session", headers=other).json() == {"state": "choose_role"}
    client.post("/api/me/role", headers=other, json=body)
    assert client.get("/api/console/database", headers=other).status_code == 403


def test_removing_an_address_from_the_list_ends_console_access(tmp_path: Path) -> None:
    allow = _allow(tmp_path, "officer@iu-example.test")
    _, client = supabase_client(tmp_path, console_allowlist=allow)
    officer = bearer("officer@iu-example.test")
    assert client.get("/api/console/database", headers=officer).status_code == 200
    allow.write_text("emails: []\n")
    _, restarted = supabase_client(tmp_path, console_allowlist=allow)
    assert restarted.get("/api/console/database", headers=officer).status_code == 401


def test_the_checked_in_allowlist_is_empty() -> None:
    from demo_server.seed import ROOT, console_emails

    assert console_emails(ROOT / "configs" / "console_allowlist.yaml") == frozenset()


def test_delete_account_also_deletes_the_supabase_auth_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from demo_server import supabase_auth

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        supabase_auth, "delete_user", lambda url, key, user_id: calls.append((url, user_id))
    )
    app, client = supabase_client(tmp_path)
    pat = bearer("pat@example.test", "user-pat")
    client.post("/api/me/role", headers=pat, json={"role": "parent", "display_name": "Pat"})
    assert client.delete("/api/me", headers=pat).status_code == 204
    assert calls == [("https://example-project.supabase.test", "user-pat")]
    assert app.state.store.account_by_email("pat@example.test") is None
    assert app.state.store.auth_deletions() == []


def test_a_failed_auth_deletion_is_kept_and_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from demo_server import supabase_auth

    def down(url: str, key: str, user_id: str) -> None:
        raise RuntimeError("auth admin HTTP 503")

    monkeypatch.setattr(supabase_auth, "delete_user", down)
    app, client = supabase_client(tmp_path)
    kim = bearer("kim@example.test", "user-kim")
    client.post("/api/me/role", headers=kim, json={"role": "student", "display_name": "Kim"})
    assert client.delete("/api/me", headers=kim).status_code == 204  # the account is gone anyway
    store = app.state.store
    assert store.account_by_email("kim@example.test") is None
    assert store.auth_deletions() == ["user-kim"]
    assert supabase_auth.retry_deletions(store, "u", "k") == 1  # still down: still pending
    monkeypatch.setattr(supabase_auth, "delete_user", lambda url, key, user_id: None)
    assert supabase_auth.retry_deletions(store, "u", "k") == 0


def test_delete_user_calls_the_admin_api_and_treats_404_as_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import urllib.error
    import urllib.request

    from demo_server import supabase_auth

    seen: list[Any] = []

    class Done(io.BytesIO):
        def __enter__(self) -> "Done":
            return self

    def fake_open(request: urllib.request.Request, timeout: float) -> Done:
        seen.append(request)
        return Done(b"")

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    key = "service-key-for-test"
    supabase_auth.delete_user("https://p.supabase.test/", key, "user 1")
    request = seen[0]
    assert request.get_method() == "DELETE"
    assert request.full_url == "https://p.supabase.test/auth/v1/admin/users/user%201"
    assert request.get_header("Apikey") == key

    def gone(request: urllib.request.Request, timeout: float) -> Done:
        raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", gone)
    supabase_auth.delete_user("https://p.supabase.test", key, "user-1")  # no error


def test_console_health_names_supabase_and_email_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow = tmp_path / "allow.yaml"
    allow.write_text("emails: [officer@iu-example.test]\n")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password-for-test")
    _, client = supabase_client(tmp_path, console_allowlist=allow, email_mode="smtp")
    found = client.get("/api/console/database", headers=bearer("officer@iu-example.test"))
    body = found.json()
    assert body["sign_in"] == "Supabase" and body["email"] == "email provider"
    text = found.text
    assert "smtp-password-for-test" not in text and "supabase.test" not in text


def test_the_websocket_refuses_a_bad_or_unknown_session(tmp_path: Path) -> None:
    from starlette.websockets import WebSocketDisconnect

    _, client = supabase_client(tmp_path)
    expired = session_token("pat@example.test", exp=1)
    no_account = session_token("nobody@example.test")
    for token in (expired, no_account, "nonsense"):
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            client.websocket_connect(f"/ws?token={token}"),
        ):
            pass
        assert closed.value.code == 4401
