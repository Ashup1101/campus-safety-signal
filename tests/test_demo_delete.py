"""Delete account: everything the account owns goes, in one step. Made-up accounts."""

from pathlib import Path

from demo_target import rows, store_at, tables
from test_demo_links import app_and_client, signed_in

ZONE = {"name": "Dorm", "lat": 39.17, "lon": -86.52, "radius_m": 300}


def test_delete_removes_every_row_the_account_owns(tmp_path: Path) -> None:
    app, client = app_and_client(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    pat = signed_in(client, store, "pat@example.test", "parent", "Pat")
    kim = signed_in(client, store, "kim@example.test", "student", "Kim")
    invite = client.post(
        "/api/invites", headers=pat, json={"student_email": "kim@example.test"}
    ).json()
    client.post(f"/api/invites/{invite['id']}/accept", headers=kim)
    client.post("/api/zones", headers=pat, json=ZONE)
    # Pilot tables (Sprint 11): a consent, the subscription and its confirm token, a survey.
    assert (
        client.post("/api/consents/digests", headers=pat, json={"granted": True}).status_code == 200
    )
    assert (
        client.post("/api/surveys/signup", headers=pat, json={"answers": [4, 4, 4]}).status_code
        == 201
    )
    pat_id = store.account_by_email("pat@example.test").id
    assert store.subscription(pat_id, "digests") == "pending_confirm"
    assert client.delete("/api/me", headers=pat).status_code == 204
    target = store_at(tmp_path / "d")
    for table in tables(target):
        for row in rows(target, table):
            assert pat_id not in row and "pat@example.test" not in row, table
    assert client.get("/api/mailbox", headers=pat).status_code == 401  # signed out
    assert store.students_of(pat_id) == []
    again = client.post(
        "/api/signup", json={"email": "pat@example.test", "role": "parent", "display_name": "Pat"}
    )
    assert again.status_code == 202  # the same email can start fresh
