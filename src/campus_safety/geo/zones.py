"""Police reporting zones from the City of Bloomington's public GIS (Law Reporting Zones).

BPD calls for service carry a reporting-zone code like LB416 and no address. The city publishes
the zone polygons with the same codes, so every call can be placed in its zone. `pull` saves the
layer as GeoJSON in bronze (only when it changed); `rows` turns the newest copy into one row per
zone with a centroid for map labels. Polygons stay as GeoJSON text; nothing finer than a zone is
ever inferred for a call.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import UTC
from typing import Any

from campus_safety import fetch
from campus_safety.geo import arcgis
from campus_safety.lake import bronze
from campus_safety.lake.parquet import Columns
from campus_safety.lake.storage import Lake

SOURCE = "city_gis_law_zones"
URL = (
    "https://bloomington.in.gov/arcgis-server/rest/services/DataPortal/DataPortal_PublicSafety/"
    "MapServer/5/query?where=1%3D1&outFields=zonecode,agencycode,distnum,sector"
    "&outSR=4326&f=geojson"
)
COLUMNS: Columns = (
    ("zonecode", "VARCHAR"),  # LB416: BPD district 4, sector 16
    ("agency_code", "VARCHAR"),  # BPD, IUPD, MCSO, EPD, SPD
    ("district", "VARCHAR"),
    ("sector", "VARCHAR"),
    ("centroid_lat", "DOUBLE"),
    ("centroid_lon", "DOUBLE"),
    ("geometry", "VARCHAR"),  # GeoJSON geometry, WGS84
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
)


class ZonesError(ValueError):
    pass


def pull(lake: Lake, run_id: str) -> tuple[bool, int]:
    """Fetch the layer; store it if it differs from the newest copy. Returns (stored, zones)."""
    page = fetch.polite_get(URL)
    zones = len(_features(page.body))
    return arcgis.store_if_changed(lake, SOURCE, page.body, URL, page, run_id), zones


def _features(body: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ZonesError("layer is not JSON") from e
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ZonesError("layer is not a GeoJSON FeatureCollection")
    return list(data.get("features") or [])


def _ring_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Area-weighted centroid (lon, lat) and absolute area of one ring, planar: zones are a few
    km across, where the distortion is far below a map label's size."""
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area == 0:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    return cx / (3 * area), cy / (3 * area), abs(area) / 2


def centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    """(lat, lon) of the largest outer ring of a Polygon or MultiPolygon."""
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        polygons: list[Any] = [coords]
    elif kind == "MultiPolygon" and isinstance(coords, list):
        polygons = coords
    else:
        raise ZonesError(f"unsupported geometry {kind!r}")
    if not polygons or not polygons[0]:
        raise ZonesError("empty geometry")
    lon, lat, _ = max((_ring_centroid(p[0]) for p in polygons), key=lambda c: c[2])
    return lat, lon


def _polygons(geometry: dict[str, Any]) -> list[Any]:
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        return [coords]
    if kind == "MultiPolygon" and isinstance(coords, list):
        return coords
    raise ZonesError(f"unsupported geometry {kind!r}")


Box = tuple[float, float, float, float]
Shape = tuple[str, Box, list[Any]]  # zone code, bounding box, polygons (rings of [lon, lat])


def shapes(zone_rows: Iterable[Sequence[object]]) -> list[Shape]:
    """Zone rows (COLUMNS order) ready for locate(); zones without a polygon are left out."""
    found: list[Shape] = []
    for row in zone_rows:
        code, geometry = row[0], row[6]
        if code and isinstance(geometry, str):
            polygons = _polygons(json.loads(geometry))
            xs = [x for polygon in polygons for x, _ in polygon[0]]
            ys = [y for polygon in polygons for _, y in polygon[0]]
            found.append((str(code), (min(xs), min(ys), max(xs), max(ys)), polygons))
    return found


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def locate(lon: float, lat: float, found: Sequence[Shape]) -> str | None:
    """The zone whose polygon holds the point (holes excluded); None outside every zone."""
    for code, (x0, y0, x1, y1), polygons in found:
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            for outer, *holes in polygons:
                if _in_ring(lon, lat, outer) and not any(_in_ring(lon, lat, h) for h in holes):
                    return code
    return None


def rows(manifest: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
    """One row per zone code. The city splits some zones into several features with the same
    code (parts on either side of a road or annexation); their parts join into one MultiPolygon."""
    parts: dict[str, list[Any]] = {}
    props_by_code: dict[str, dict[str, Any]] = {}
    for feature in _features(body):
        props = feature.get("properties") or {}
        code = str(props.get("zonecode") or "").strip()
        shape = feature.get("geometry")
        if not code or not shape:
            continue
        parts.setdefault(code, []).extend(_polygons(shape))
        props_by_code.setdefault(code, props)
    found: list[tuple[object, ...]] = []
    for code, polygons in parts.items():
        props = props_by_code[code]
        merged: dict[str, Any] = (
            {"type": "Polygon", "coordinates": polygons[0]}
            if len(polygons) == 1
            else {"type": "MultiPolygon", "coordinates": polygons}
        )
        lat, lon = centroid(merged)
        found.append(
            (
                code,
                str(props.get("agencycode") or "").strip(),
                str(props.get("distnum") or "").strip() or None,
                str(props.get("sector") or "").strip() or None,
                round(lat, 6),
                round(lon, 6),
                json.dumps(merged, separators=(",", ":")),
                manifest.key,
                manifest.run_id,
                manifest.fetched_at.astimezone(UTC).replace(tzinfo=None),
            )
        )
    return found
