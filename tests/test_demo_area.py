"""An alert's map area comes only from streets the official text names. Made-up alert texts."""

from pathlib import Path

from fastapi.testclient import TestClient

from demo_server.activity import load_geojson
from demo_server.app import create_app
from demo_server.area import area_for
from demo_server.seed import Settings

NAMES = {f["properties"]["id"]: f["properties"]["name"] for f in load_geojson()["features"]}
KIRKWOOD = ["kirkwood_100", "kirkwood_200", "kirkwood_300", "kirkwood_400", "kirkwood_500"]


def test_a_named_street_maps_to_its_segments() -> None:
    assert area_for("DRILL: Shelter in place, avoid Kirkwood Avenue.", NAMES) == KIRKWOOD


def test_a_named_block_narrows_to_that_block() -> None:
    text = "Police activity in the 400 block of E Kirkwood Ave. Avoid the area."
    assert area_for(text, NAMES) == ["kirkwood_400"]


def test_ordinal_words_and_numbers_both_match() -> None:
    expected = ["e3rd_east_eagleson", "e3rd_west_eagleson"]
    assert area_for("Avoid Third Street near campus.", NAMES) == expected
    assert area_for("Avoid E 3rd St.", NAMES) == expected


def test_a_name_that_is_not_written_as_a_street_never_matches() -> None:
    assert area_for("Indiana University police are responding.", NAMES) == []
    assert area_for("Stay inside. More information soon.", NAMES) == []
    assert area_for("", NAMES) == []


def test_the_drill_alert_and_the_alert_list_carry_the_area(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "demo",
        warehouse=tmp_path / "missing.duckdb",
        manual=tmp_path / "missing.yaml",
        tiles=tmp_path / "tiles",
    )
    client = TestClient(create_app(settings))
    with client:
        token = client.post("/api/login", json={"account_id": "console"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        with client.websocket_connect(f"/ws?token={token}") as console:
            console.receive_json()
            client.post("/api/drill", json={"action": "drill"}, headers=headers)
            assert console.receive_json()["alert"]["area"] == KIRKWOOD
        assert client.get("/api/alerts", headers=headers).json()[0]["area"] == KIRKWOOD
