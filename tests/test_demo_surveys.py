"""Short surveys (Sprint 11): three 1-5 answers, numbers only, one per prompt. Made-up accounts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campus_safety.official.alerts import OfficialAlert
from demo_server.app import create_app
from demo_server.seed import Settings


@pytest.fixture
def app(tmp_path: Path) -> object:
    return create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )


def auth(client: TestClient, who: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": who}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def alert(status: str) -> OfficialAlert:
    return OfficialAlert("feed", "web_page", "DRILL: test.", "drill", None, status)


def test_signup_survey_once_with_numbers_only(app: object) -> None:
    client = TestClient(app)  # type: ignore[arg-type]
    sam = auth(client, "student_sam")
    due = client.get("/api/surveys/due", headers=sam).json()
    assert [d["prompt"] for d in due] == ["signup"] and len(due[0]["questions"]) == 3
    assert (
        client.post("/api/surveys/signup", headers=sam, json={"answers": [5, 4, 9]}).status_code
        == 422
    )
    assert (
        client.post("/api/surveys/signup", headers=sam, json={"answers": [5, 4, 3]}).status_code
        == 201
    )
    assert (
        client.post("/api/surveys/signup", headers=sam, json={"answers": [1, 1, 1]}).status_code
        == 409
    )
    assert client.get("/api/surveys/due", headers=sam).json() == []


def test_after_alert_survey_a_day_after_the_card_closes_and_can_be_skipped(app: object) -> None:
    client = TestClient(app)  # type: ignore[arg-type]
    store = app.state.store  # type: ignore[attr-defined]
    now = datetime.now(UTC)
    store.add_alert("a1", alert("Severe"), now - timedelta(hours=30), "t1")
    store.add_alert("a2", alert("Normal"), now - timedelta(hours=26), "t1")
    store.delivered("a1", "student_sam", "ios", now - timedelta(hours=30))
    store.add_alert("b1", alert("Normal"), now - timedelta(hours=2), "t2")  # closed too recently
    store.delivered("b1", "student_sam", "ios", now - timedelta(hours=2))
    sam = auth(client, "student_sam")
    client.post("/api/surveys/signup", headers=sam, json={"skip": True})
    due = [d["prompt"] for d in client.get("/api/surveys/due", headers=sam).json()]
    assert due == ["after_alert:t1"]
    assert (
        client.post("/api/surveys/after_alert:t1", headers=sam, json={"skip": True}).status_code
        == 201
    )
    assert client.get("/api/surveys/due", headers=sam).json() == []
    assert (
        client.get("/api/surveys/due", headers=auth(client, "parent_dad")).json()[0]["prompt"]
        == "signup"
    )
