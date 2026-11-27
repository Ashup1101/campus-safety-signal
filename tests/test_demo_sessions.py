"""Background sessions: events only, never coordinates; linked parents only; nothing stored."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from demo_server.app import create_app
from demo_server.seed import Settings

SID = "session-abc12345"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t"
    )
    return TestClient(create_app(settings))


def auth(client: TestClient, who: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": who}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def street(client: TestClient) -> str:
    hub = client.app.state.hub  # type: ignore[attr-defined]
    return str(next(iter(hub._segments)))


def heard_by_parents(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    hub = client.app.state.hub  # type: ignore[attr-defined]
    heard: list[dict[str, Any]] = []

    async def capture(student_id: str, message: dict[str, Any]) -> None:
        heard.append({"to_parents_of": student_id, **message})

    monkeypatch.setattr(hub, "_to_parents", capture)
    return heard


def post(client: TestClient, who: dict[str, str], **body: Any) -> Any:
    return client.post("/api/sessions/events", headers=who, json={"session_id": SID, **body})


def test_events_reach_linked_parents_once_and_nothing_else(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    heard = heard_by_parents(client, monkeypatch)
    sam = auth(client, "student_sam")  # demo personas come with every consent
    client.post("/api/consents/background_location", headers=sam, json={"granted": True})
    assert post(client, sam, kind="started").status_code == 202
    segment = street(client)
    assert post(client, sam, kind="heads_up", segment_id=segment).status_code == 202
    assert post(client, sam, kind="heads_up", segment_id=segment).json() == {
        "status": "already sent"
    }
    assert post(client, sam, kind="arrived_home").status_code == 202
    assert post(client, sam, kind="ended", reason="arrived").status_code == 202
    assert [m["type"] for m in heard] == ["heads_up", "arrived_home"]
    assert all(m["to_parents_of"] == "student_sam" for m in heard)
    assert not any(k in m for m in heard for k in ("lat", "lon", "latitude", "longitude"))
    counts = client.app.state.sessions.counts  # type: ignore[attr-defined]
    assert counts == {"started": 1, "heads_up": 1, "arrived_home": 1, "ended_arrived": 1}


@pytest.mark.parametrize(
    "extra", [{"lat": 39.1}, {"lon": -86.5}, {"location": "x"}, {"accuracy": 5}]
)
def test_any_coordinate_or_extra_field_is_refused(
    client: TestClient, extra: dict[str, Any]
) -> None:
    sam = auth(client, "student_sam")
    client.post("/api/consents/background_location", headers=sam, json={"granted": True})
    assert post(client, sam, kind="started", **extra).status_code == 422


def test_parents_and_other_students_cannot_send_events(client: TestClient) -> None:
    mom = auth(client, "parent_mom")
    assert post(client, mom, kind="started").status_code == 403
    sam, alex = auth(client, "student_sam"), auth(client, "student_alex")
    for who in (sam, alex):
        client.post("/api/consents/background_location", headers=who, json={"granted": True})
    post(client, sam, kind="started")
    assert post(client, alex, kind="arrived_home").status_code == 404  # not Alex's session
    assert post(client, sam, kind="heads_up", segment_id="no_such_street").status_code == 400


def test_nothing_about_sessions_is_stored(client: TestClient, tmp_path: Path) -> None:
    from demo_target import store_at, tables

    sam = auth(client, "student_sam")
    client.post("/api/consents/background_location", headers=sam, json={"granted": True})
    post(client, sam, kind="started")
    assert not [t for t in tables(store_at(tmp_path / "d")) if "session" in t]
    asyncio.run(asyncio.sleep(0))


def test_a_real_student_must_say_yes_first(tmp_path: Path) -> None:
    from test_demo_links import app_and_client, signed_in

    app, client = app_and_client(tmp_path)
    kim = signed_in(client, app.state.store, "kim@example.test", "student", "Kim")  # type: ignore[attr-defined]
    assert post(client, kim, kind="started").status_code == 403
    client.post("/api/consents/background_location", headers=kim, json={"granted": True})
    assert post(client, kim, kind="started").status_code == 202
