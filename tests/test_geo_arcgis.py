"""Paged, bbox-limited, polite reads of city layers; stored only when changed. Made-up features."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from campus_safety import fetch
from campus_safety.geo import arcgis
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake


def point(i: int) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"id": i},
        "geometry": {"type": "Point", "coordinates": [-86.5, 39.16]},
    }


def test_query_url_limits_to_the_box_and_pages() -> None:
    url = arcgis.query_url("DataPortal/X", 4, ("a", "b"), (-86.6, 39.1, -86.4, 39.2), offset=2000)
    query = parse_qs(urlsplit(url).query)
    assert url.startswith(arcgis.BASE + "DataPortal/X/MapServer/4/query?")
    assert query["geometry"] == ["-86.6,39.1,-86.4,39.2"] and query["inSR"] == ["4326"]
    assert query["resultOffset"] == ["2000"] and query["outFields"] == ["a,b"]


def test_fetch_layer_merges_pages_and_stores_only_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(arcgis, "PAGE_SIZE", 2)
    pages = {0: [point(1), point(2)], 2: [point(3)]}
    asked: list[int] = []

    def fake(url: str, **kwargs: object) -> fetch.Page:
        offset = int(parse_qs(urlsplit(url).query)["resultOffset"][0])
        asked.append(offset)
        body = json.dumps({"type": "FeatureCollection", "features": pages.get(offset, [])})
        return fetch.Page(url, body.encode(), datetime.now(UTC))

    monkeypatch.setattr(fetch, "polite_get", fake)
    body, url, page = arcgis.fetch_layer("DataPortal/X", 4, ("id",))
    assert asked == [0, 2]
    assert [f["properties"]["id"] for f in arcgis.features(body)] == [1, 2, 3]
    lake = FileLake(tmp_path / "lake")
    assert arcgis.store_if_changed(lake, "city_x", body, url, page, "r1")
    assert not arcgis.store_if_changed(lake, "city_x", body, url, page, "r2")
    assert len(bronze.manifests(lake, "city_x")) == 1
    with pytest.raises(arcgis.LayerError):
        arcgis.features(b'{"type": "Feature"}')
