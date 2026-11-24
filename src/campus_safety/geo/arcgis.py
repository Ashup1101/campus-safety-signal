"""Polite reads of the City of Bloomington's public ArcGIS layers (honest User-Agent, robots.txt
first, through campus_safety.fetch), paged and limited to a bounding box, stored in bronze only
when the merged layer changed. Logs carry counts only."""

import hashlib
import json
from typing import Any
from urllib.parse import urlencode

from campus_safety import fetch
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

BASE = "https://bloomington.in.gov/arcgis-server/rest/services/"
PAGE_SIZE = 1000
MAX_PAGES = 50  # 50k features: far above any campus/downtown layer; a runaway loop stops here

# Campus and downtown Bloomington (lon/lat, WGS84): Walnut St to the stadium, 2nd St to 17th St.
CAMPUS_DOWNTOWN = (-86.545, 39.155, -86.495, 39.190)


class LayerError(ValueError):
    pass


def query_url(
    service: str,
    layer: int,
    fields: tuple[str, ...],
    bbox: tuple[float, float, float, float] | None = None,
    offset: int = 0,
) -> str:
    params: dict[str, str | int] = {
        "where": "1=1",
        "outFields": ",".join(fields),
        "outSR": 4326,
        "f": "geojson",
        "orderByFields": "OBJECTID",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    if bbox:
        params |= {
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        }
    return f"{BASE}{service}/MapServer/{layer}/query?{urlencode(params)}"


def features(body: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise LayerError("layer is not JSON") from e
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise LayerError("layer is not a GeoJSON FeatureCollection")
    return list(data.get("features") or [])


def fetch_layer(
    service: str,
    layer: int,
    fields: tuple[str, ...],
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[bytes, str, fetch.Page]:
    """All pages merged into one FeatureCollection (stable bytes, so unchanged layers hash the
    same). Returns (body, first-page URL, last page)."""
    found: list[dict[str, Any]] = []
    first = query_url(service, layer, fields, bbox)
    page: fetch.Page | None = None
    for number in range(MAX_PAGES):
        page = fetch.polite_get(query_url(service, layer, fields, bbox, number * PAGE_SIZE))
        batch = features(page.body)
        found.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    else:
        raise LayerError(f"more than {MAX_PAGES} pages")
    if page is None:  # MAX_PAGES >= 1, so a page was always read
        raise LayerError("no pages read")
    merged = {"type": "FeatureCollection", "features": found}
    return json.dumps(merged, sort_keys=True, separators=(",", ":")).encode(), first, page


def store_if_changed(
    lake: Lake, source: str, body: bytes, url: str, page: fetch.Page, run_id: str
) -> bool:
    found = bronze.manifests(lake, source)
    if found and found[-1].sha256 == hashlib.sha256(body).hexdigest():
        return False
    bronze.write(
        lake,
        source=source,
        body=body,
        url=url,
        fetched_at=page.fetched_at,
        http_status=page.status,
        run_id=run_id,
        ext="geojson",
    )
    return True
