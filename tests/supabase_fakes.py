"""Supabase sign-in for tests: HS256 tokens made with a per-run secret (no network, no project)."""

import secrets
import time
from pathlib import Path
from typing import Any

import jwt
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings

PROJECT = "https://example-project.supabase.test"
SECRET = secrets.token_urlsafe(32)


def supabase_settings(tmp_path: Path, **extra: Any) -> Settings:
    return Settings(
        data_dir=tmp_path / "d",
        warehouse=tmp_path / "n.duckdb",
        tiles=tmp_path / "t",
        auth_mode="supabase",
        supabase_url=PROJECT,
        supabase_jwt_secret=SECRET,
        **extra,
    )


def supabase_client(tmp_path: Path, **extra: Any) -> tuple[Any, TestClient]:
    app = create_app(supabase_settings(tmp_path, **extra))
    return app, TestClient(app)


def session_token(email: str, user_id: str | None = None, **claims: Any) -> str:
    body = {
        "sub": user_id or f"user-{email}",
        "email": email,
        "aud": "authenticated",
        "iss": f"{PROJECT}/auth/v1",
        "exp": int(time.time()) + 3600,
    } | claims
    return jwt.encode(body, SECRET, algorithm="HS256")


def bearer(email: str, user_id: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(email, user_id)}"}
