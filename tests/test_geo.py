"""Phase 3: police reporting zones from the city GIS place BPD calls on the map. All geometry
and calls are made up."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from test_bpd_cfs import portal  # noqa: F401 (fixture)

from campus_safety import fetch
from campus_safety.bpd_cfs import pull as bpd_pull
from campus_safety.geo import zones
from campus_safety.geo.cli import main
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake
from campus_safety.lake.transform import transform


def square(lon: float, lat: float, size: float) -> list[list[float]]:
    return [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]


def layer(*features: dict[str, object]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": list(features)}).encode()


def zone(
    code: str, agency: str = "BPD", ring: list[list[float]] | None = None
) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"zonecode": code, "agencycode": agency, "distnum": "1", "sector": "1"},
        "geometry": {"type": "Polygon", "coordinates": [ring or square(-86.53, 39.16, 0.01)]},
    }


LAYER = layer(zone("LB101"), zone("LI901", "IUPD", square(-86.52, 39.17, 0.002)))


def test_centroids() -> None:
    lat, lon = zones.centroid({"type": "Polygon", "coordinates": [square(-86.53, 39.16, 0.01)]})
    assert (round(lat, 6), round(lon, 6)) == (39.165, -86.525)
    multi = {
        "type": "MultiPolygon",
        "coordinates": [[square(0, 0, 1)], [square(10, 10, 4)]],  # the larger part wins
    }
    assert zones.centroid(multi) == (12.0, 12.0)
    with pytest.raises(zones.ZonesError):
        zones.centroid({"type": "Point", "coordinates": [0, 0]})


def manifest() -> bronze.Manifest:
    at = datetime(2026, 11, 14, tzinfo=UTC)
    return bronze.Manifest(zones.SOURCE, "bronze/k", zones.URL, at, "0" * 64, 200, "r1")


def test_rows_and_layout_errors() -> None:
    found = zones.rows(manifest(), LAYER)
    assert [(r[0], r[1], r[4], r[5]) for r in found] == [
        ("LB101", "BPD", 39.165, -86.525),
        ("LI901", "IUPD", 39.171, -86.519),
    ]
    assert json.loads(str(found[0][6]))["type"] == "Polygon"
    split = zones.rows(
        manifest(), layer(zone("LB101"), zone("LB101", ring=square(-86.50, 39.16, 0.02)))
    )
    assert len(split) == 1 and json.loads(str(split[0][6]))["type"] == "MultiPolygon"
    assert split[0][4:6] == (39.17, -86.49)  # the larger part's centroid
    with pytest.raises(zones.ZonesError, match="FeatureCollection"):
        zones.rows(manifest(), b'{"type": "Feature"}')


@pytest.fixture
def city(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    served = {zones.URL: LAYER}
    original = fetch.polite_get

    def fake(url: str, **kwargs: object) -> fetch.Page:
        if url in served:
            return fetch.Page(url, served[url], datetime.now(UTC))
        return original(url)  # the BPD portal fixture, when also active

    monkeypatch.setattr(fetch, "polite_get", fake)
    return served


def test_pull_stores_only_changes(city: dict[str, bytes], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    assert zones.pull(lake, "r1") == (True, 2)
    assert zones.pull(lake, "r2") == (False, 2)
    city[zones.URL] = layer(zone("LB101"))
    assert zones.pull(lake, "r3") == (True, 1)
    assert len(bronze.manifests(lake, zones.SOURCE)) == 2


def test_cli(city: dict[str, bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKE_URI", FileLake(tmp_path / "lake").uri)
    assert main(["pull"]) == 0
    city[zones.URL] = b"not json"
    assert main(["pull"]) == 1


def test_bpd_calls_land_in_their_zones(
    portal: list[str],  # noqa: F811
    city: dict[str, bytes],
    tmp_path: Path,
) -> None:
    lake = FileLake(tmp_path / "lake")
    bpd_pull.pull(lake, "local-abc", page_size=3, delay=0, sleep=lambda _: None)
    zones.pull(lake, "r1")
    transform(lake, tmp_path / "work")
    with duckdb.connect(str(tmp_path / "work" / "warehouse.duckdb")) as con:
        found = con.execute(
            "SELECT zonecode, has_geometry, calls, centroid_lat FROM gold.bpd_zone_calls ORDER BY 1"
        ).fetchall()
        published = con.execute("SELECT count(*) FROM silver.geo_law_zones").fetchone()
    # LB101 has 2 calls and a polygon; LB2 is a code with no zone in the layer; the IUPD zone has
    # no calls yet but stays on the map with a zero count.
    assert found == [
        ("LB101", True, 2, 39.165),
        ("LB2", False, 1, None),
        ("LI901", True, 0, 39.171),
    ]
    assert published == (2,)
    assert (tmp_path / "lake" / "gold" / "bpd_zone_calls.parquet").exists()
