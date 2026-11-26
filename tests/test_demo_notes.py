"""Community notes on the demo server. Made-up accounts, incidents and words."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from demo_target import columns, store_at, tables

from demo_server.seed import ACCOUNTS
from demo_server.store import Store

NOW = datetime(2026, 11, 26, 23, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    return store


def test_notes_tables_hold_no_location(store: Store, tmp_path: Path) -> None:
    for table in ("notes", "note_reports", "bans", "settings"):
        found = columns(store_at(tmp_path), table)
        assert found, table
        assert not found & {"lat", "lon", "latitude", "longitude", "location", "distance_m"}


def test_one_note_per_person_per_incident(store: Store) -> None:
    first = store.put_note("t1", "student_sam", "Police on scene", None, "pending", NOW)
    again = store.put_note("t1", "student_sam", "Road closed", "Dunn closed", "pending", NOW)
    assert first == again  # an edit, not a second note
    [note] = store.notes_of("t1")
    assert (note["tag"], note["text"], note["account_id"]) == (
        "Road closed",
        "Dunn closed",
        "student_sam",
    )
    store.set_note_state(first, "hidden")
    assert store.note(first)["state"] == "hidden"  # type: ignore[index]
    assert store.delete_note(first) and store.notes_of("t1") == []


def test_reports_bans_settings_and_delete(store: Store) -> None:
    note = store.put_note("t1", "student_sam", "Police on scene", None, "visible", NOW)
    assert store.add_report(note, "student_alex") and not store.add_report(note, "student_alex")
    assert store.report_count(note) == 1
    store.ban("student_sam", NOW + timedelta(days=7))
    assert store.banned("student_sam", NOW) and not store.banned(
        "student_sam", NOW + timedelta(days=8)
    )
    assert store.setting("notes_enabled", "on") == "on"
    store.set_setting("notes_enabled", "off")
    assert store.setting("notes_enabled", "on") == "off"
    sam = store.account("student_sam")
    assert sam is not None
    store.delete_account(sam)
    assert store.notes_of("t1") == [] and not store.banned("student_sam", NOW)


# --- posting through the API ---

from typing import Any  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from campus_safety.official.alerts import OfficialAlert  # noqa: E402
from demo_server import notes_api  # noqa: E402
from demo_server.app import create_app  # noqa: E402
from demo_server.seed import Settings  # noqa: E402

KIRKWOOD_400 = {"lat": 39.16655, "lon": -86.5290}  # on the hand-drawn 400 block
FAR = {"lat": 39.20, "lon": -86.60}


def alert(status: str) -> OfficialAlert:
    return OfficialAlert(
        source="feed",
        kind="web_page",
        text="DRILL: Police activity in the 400 block of E Kirkwood Ave. Avoid the area.",
        verification="drill",
        official_at=None,
        status=status,
    )


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, TestClient]:
    monkeypatch.setattr(notes_api, "names_detector", lambda text: [])
    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    return app, TestClient(app)


def auth(client: TestClient, who: str) -> dict[str, str]:
    token = client.post("/api/login", json={"account_id": who}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def post(client: TestClient, who: str, body: dict[str, Any], method: str = "post") -> Any:
    return client.request(
        method.upper(), "/api/threads/t1/note", headers=auth(client, who), json=body
    )


def test_students_nearby_post_one_note_and_can_edit_or_withdraw(
    api: tuple[Any, TestClient],
) -> None:
    app, client = api
    store = app.state.store
    now = datetime.now(UTC)  # the API checks expiry against the real clock
    store.add_alert("a1", alert("Severe"), now - timedelta(minutes=5), "t1")
    store.add_alert("a2", alert("Normal"), now - timedelta(minutes=1), "t1")  # all-clear
    made = post(
        client, "student_sam", {"tag": "Road closed", "text": "Dunn closed", **KIRKWOOD_400}
    )
    assert made.status_code == 201 and made.json()["state"] == "pending"
    edited = post(client, "student_sam", {"tag": "Area reopened", **KIRKWOOD_400}, "put")
    assert edited.json()["id"] == made.json()["id"]
    assert [n["tag"] for n in store.notes_of("t1")] == ["Area reopened"]
    assert post(client, "student_sam", {}, "delete").status_code == 204
    assert store.notes_of("t1") == []


def test_who_and_where_may_post(api: tuple[Any, TestClient]) -> None:
    app, client = api
    store = app.state.store
    store.add_alert("a1", alert("Severe"), datetime.now(UTC), "t1")
    body = {"tag": "Police on scene", **KIRKWOOD_400}
    assert post(client, "parent_mom", body).status_code == 403  # parents read only
    assert post(client, "student_sam", {**body, **FAR}).json()["detail"] == "not near this area"
    store.ban("student_alex", datetime.now(UTC) + timedelta(days=1))
    assert post(client, "student_alex", body).status_code == 403
    live = post(client, "student_sam", {"tag": "Crowd gathering", **KIRKWOOD_400})
    assert live.json()["detail"] == "only safety tags during a live alert"
    blocked = {"tag": "Police on scene", "text": "call 812-555-0100", **KIRKWOOD_400}
    assert post(client, "student_sam", blocked).json()["detail"] == "text waits for IU's all-clear"
    assert post(client, "student_sam", body).status_code == 201
    other = client.post("/api/threads/nope/note", headers=auth(client, "student_sam"), json=body)
    assert other.status_code == 404


def test_text_checks_after_the_all_clear(api: tuple[Any, TestClient]) -> None:
    app, client = api
    app.state.store.add_alert("a1", alert("Normal"), datetime.now(UTC), "t1")
    phone = {"tag": "Road closed", "text": "call 812-555-0100", **KIRKWOOD_400}
    assert post(client, "student_sam", phone).json()["detail"] == "phone number"
    held = post(
        client, "student_sam", {"tag": "Road closed", "text": "heard a shooter", **KIRKWOOD_400}
    )
    assert held.json()["state"] == "held"


def test_readers_see_only_confirmed_notes_without_who(api: tuple[Any, TestClient]) -> None:
    app, client = api
    app.state.store.add_alert("a1", alert("Normal"), datetime.now(UTC), "t1")
    road = {"tag": "Road closed", "text": "Dunn closed", **KIRKWOOD_400}
    assert post(client, "student_sam", road).status_code == 201

    def read(who: str) -> dict[str, Any]:
        found = client.get("/api/threads/t1/notes", headers=auth(client, who))
        return dict(found.json())

    first = read("parent_mom")
    assert first["notes"] == [] and first["label"] == "Community notes (unverified)"
    assert read("student_sam")["mine"]["state"] == "pending"  # the poster sees their own
    assert post(client, "student_alex", {"tag": "Road closed", **KIRKWOOD_400}).status_code == 201
    shown = read("parent_mom")
    [group] = shown["notes"]
    assert (group["tag"], group["people"], group["by"]) == ("Road closed", 2, "IU student nearby")
    assert [t["text"] for t in group["texts"]] == ["Dunn closed"] and len(group["ids"]) == 2
    assert "student_sam" not in str(shown) and shown["mine"] is None
    app.state.store.set_setting("notes_enabled", "off")
    assert read("parent_mom")["notes"] == []  # kill switch hides everything


def test_three_reports_hide_a_note_and_nobody_reports_twice(api: tuple[Any, TestClient]) -> None:
    app, client = api
    store = app.state.store
    store.add_alert("a1", alert("Normal"), datetime.now(UTC), "t1")
    note = post(
        client, "student_sam", {"tag": "Road closed", "text": "Dunn closed", **KIRKWOOD_400}
    )
    note_id = note.json()["id"]

    def report(who: str) -> Any:
        return client.post(f"/api/notes/{note_id}/report", headers=auth(client, who))

    assert report("student_sam").status_code == 400  # not your own
    assert report("parent_mom").json() == {"hidden": False}
    assert report("parent_mom").status_code == 409  # once per person
    assert report("parent_dad").json() == {"hidden": False}
    assert report("student_alex").json() == {"hidden": True}
    assert store.note(note_id)["state"] == "hidden"
    assert (
        client.post("/api/notes/999/report", headers=auth(client, "parent_mom")).status_code == 404
    )


def test_moderators_hide_unhide_and_ban_by_note(api: tuple[Any, TestClient]) -> None:
    app, client = api
    store = app.state.store
    store.add_alert("a1", alert("Normal"), datetime.now(UTC), "t1")
    console, mom = auth(client, "console"), auth(client, "parent_mom")
    held = post(
        client, "student_sam", {"tag": "Road closed", "text": "heard a shooter", **KIRKWOOD_400}
    )
    held_id = held.json()["id"]
    assert client.get("/api/console/notes/queue", headers=mom).status_code == 403
    [queued] = client.get("/api/console/notes/queue", headers=console).json()
    assert (queued["id"], queued["state"], queued["text"]) == (held_id, "held", "heard a shooter")
    assert "account_id" not in queued  # moderators act on notes, never see who
    assert client.post(f"/api/console/notes/{held_id}/unhide", headers=console).status_code == 200
    assert store.note(held_id)["state"] == "pending"
    assert client.post(f"/api/console/notes/{held_id}/hide", headers=console).status_code == 200
    assert store.note(held_id)["state"] == "hidden"
    assert client.post(f"/api/console/notes/{held_id}/ban", headers=console).status_code == 200
    assert store.notes_of("t1") == []  # a ban removes the person's notes
    again = post(client, "student_sam", {"tag": "Road closed", **KIRKWOOD_400})
    assert again.status_code == 403


def test_the_kill_switch_hides_everything_and_blocks_posting(api: tuple[Any, TestClient]) -> None:
    app, client = api
    app.state.store.add_alert("a1", alert("Normal"), datetime.now(UTC), "t1")
    console = auth(client, "console")
    for who in ("student_sam", "student_alex"):
        post(client, who, {"tag": "Road closed", **KIRKWOOD_400})
    assert client.get("/api/console/notes/switch", headers=console).json() == {"enabled": True}
    off = client.post("/api/console/notes/switch", headers=console, json={"enabled": False})
    assert off.json() == {"enabled": False}
    reader = auth(client, "parent_mom")
    assert client.get("/api/threads/t1/notes", headers=reader).json()["notes"] == []
    assert (
        post(client, "student_sam", {"tag": "Road closed", **KIRKWOOD_400}, "put").status_code
        == 403
    )
    client.post("/api/console/notes/switch", headers=console, json={"enabled": True})
    assert len(client.get("/api/threads/t1/notes", headers=reader).json()["notes"]) == 1
    assert (
        client.post(
            "/api/console/notes/switch",
            headers=auth(client, "student_sam"),
            json={"enabled": False},
        ).status_code
        == 403
    )


def test_notes_vanish_a_day_after_the_incident_closes(store: Store, tmp_path: Path) -> None:
    opened = NOW - timedelta(days=3)
    store.add_alert("a1", alert("Severe"), opened, "closed")
    store.add_alert("a2", alert("Normal"), opened + timedelta(hours=1), "closed")
    store.add_alert("a3", alert("Severe"), NOW - timedelta(hours=2), "open")
    store.add_alert("a4", alert("Severe"), NOW - timedelta(hours=31), "grey")  # no all-clear
    for thread in ("closed", "open", "grey"):
        store.put_note(thread, "student_sam", "Road closed", None, "pending", opened)
    assert store.expire_notes(NOW - timedelta(days=2) + timedelta(minutes=30), hours=24) == 0
    # A day after the all-clear; a day after the grey card went quiet (6 h without an update).
    assert store.expire_notes(NOW, hours=24) == 2
    assert [store.notes_of(t) != [] for t in ("closed", "open", "grey")] == [False, True, False]
    assert [t for t in tables(store_at(tmp_path)) if "history" in t] == []


def test_the_composer_gets_the_tag_lists(api: tuple[Any, TestClient]) -> None:
    _, client = api
    found = client.get("/api/notes/config", headers=auth(client, "student_sam")).json()
    assert "Police on scene" in found["safety_tags"] and found["text_limit"] == 140


def test_no_notes_on_an_incident_that_went_quiet_long_ago(api: tuple[Any, TestClient]) -> None:
    app, client = api
    quiet = datetime.now(UTC) - timedelta(hours=40)  # no all-clear, 6 h + 24 h ago
    app.state.store.add_alert("a1", alert("Severe"), quiet, "t1")
    assert (
        post(client, "student_sam", {"tag": "Police on scene", **KIRKWOOD_400}).status_code == 404
    )
