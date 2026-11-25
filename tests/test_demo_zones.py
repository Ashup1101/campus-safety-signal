"""Watch zones: each account edits only its own, within limits. Made-up places."""

from pathlib import Path

from test_demo_links import app_and_client, signed_in

ZONE = {"name": "Near the dorm", "lat": 39.1700, "lon": -86.5200, "radius_m": 400}


def test_own_zones_only_with_limits(tmp_path: Path) -> None:
    app, client = app_and_client(tmp_path)
    store = app.state.store  # type: ignore[attr-defined]
    pat = signed_in(client, store, "pat@example.test", "parent", "Pat")
    lee = signed_in(client, store, "lee@example.test", "parent", "Lee")
    made = client.post("/api/zones", headers=pat, json=ZONE)
    assert made.status_code == 201
    zone_id = made.json()["id"]
    assert [z["name"] for z in client.get("/api/zones", headers=pat).json()] == ["Near the dorm"]
    renamed = client.put(f"/api/zones/{zone_id}", headers=pat, json={**ZONE, "name": "Dorm"})
    assert renamed.status_code == 200
    assert client.put(f"/api/zones/{zone_id}", headers=lee, json=ZONE).status_code == 404
    assert client.delete(f"/api/zones/{zone_id}", headers=lee).status_code == 404
    for radius in (99, 2001):
        assert (
            client.post("/api/zones", headers=pat, json={**ZONE, "radius_m": radius}).status_code
            == 422
        )
    for _ in range(4):
        assert client.post("/api/zones", headers=pat, json=ZONE).status_code == 201
    assert client.post("/api/zones", headers=pat, json=ZONE).status_code == 409  # five at most
    assert client.delete(f"/api/zones/{zone_id}", headers=pat).status_code == 204
    assert len(client.get("/api/zones", headers=pat).json()) == 4
