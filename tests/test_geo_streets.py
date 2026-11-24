"""Street network layers come from the city's GIS inside the campus/downtown box. Made-up data."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from campus_safety import fetch
from campus_safety.geo import streets
from campus_safety.geo.cli import main
from campus_safety.lake import bronze
from campus_safety.lake.storage import FileLake


@pytest.fixture
def city(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def fake(url: str, **kwargs: object) -> fetch.Page:
        asked.append(url)
        query = parse_qs(urlsplit(url).query)
        feature = {"type": "Feature", "properties": {"f": query["outFields"][0]}, "geometry": None}
        body = json.dumps({"type": "FeatureCollection", "features": [feature]}).encode()
        return fetch.Page(url, body, datetime.now(UTC))

    monkeypatch.setattr(fetch, "polite_get", fake)
    return asked


def test_pull_reads_three_layers_in_the_box_once_each(city: list[str], tmp_path: Path) -> None:
    lake = FileLake(tmp_path / "lake")
    found = streets.pull(lake, "r1")
    assert found == {layer.source: (True, 1) for layer in streets.LAYERS}
    assert all("geometryType=esriGeometryEnvelope" in url for url in city)
    assert streets.pull(lake, "r2") == {layer.source: (False, 1) for layer in streets.LAYERS}
    assert all(len(bronze.manifests(lake, layer.source)) == 1 for layer in streets.LAYERS)


def test_cli_pull_streets(city: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKE_URI", FileLake(tmp_path / "lake").uri)
    assert main(["pull-streets"]) == 0
