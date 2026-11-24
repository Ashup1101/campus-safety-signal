"""The city's street network for campus and downtown: road centerlines (names, address ranges,
cross streets), named intersections, and address points. Public City of Bloomington GIS layers,
read politely (geo.arcgis) and stored in bronze only when they change. Incidents are placed on
these in later steps; nothing here touches incident data."""

import json
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from campus_safety.geo import arcgis
from campus_safety.geo.normalize import street_key
from campus_safety.lake import bronze
from campus_safety.lake.parquet import Columns
from campus_safety.lake.storage import Lake

PROVENANCE: Columns = (
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
)
STREETS: Columns = (
    ("objectid", "BIGINT"),
    ("fullname", "VARCHAR"),  # E 10TH ST
    ("street_key", "VARCHAR"),  # 10TH
    ("lowadd", "INTEGER"),
    ("highadd", "INTEGER"),
    ("lowxst", "VARCHAR"),  # cross street at the low-address end
    ("highxst", "VARCHAR"),
    ("geometry", "VARCHAR"),  # GeoJSON LineString / MultiLineString, WGS84
    *PROVENANCE,
)
INTERSECTIONS: Columns = (
    ("objectid", "BIGINT"),
    ("intname", "VARCHAR"),  # E 10TH ST & N JORDAN AVE
    ("street_a", "VARCHAR"),
    ("street_b", "VARCHAR"),
    ("lat", "DOUBLE"),
    ("lon", "DOUBLE"),
    *PROVENANCE,
)
ADDRESSES: Columns = (
    ("street_number", "INTEGER"),
    ("street_direction", "VARCHAR"),
    ("street_key", "VARCHAR"),
    ("lat", "DOUBLE"),
    ("lon", "DOUBLE"),
    *PROVENANCE,
)


@dataclass(frozen=True)
class Layer:
    source: str
    service: str
    layer: int
    fields: tuple[str, ...]
    order: str


LAYERS = (
    Layer(
        "city_gis_streets",
        "DataPortal/DataPortal_Transportation",
        4,  # Road Centerlines
        (
            "objectid",
            "fullname",
            "stdir",
            "stname",
            "stsuffix",
            "lowadd",
            "highadd",
            "lowxst",
            "highxst",
        ),
        "objectid",
    ),
    Layer(
        "city_gis_intersections",
        "Locators/LocalSearch",
        1,  # Intersections_LocalSearch: "E 10TH ST & N JORDAN AVE"
        ("OBJECTID", "intname"),
        "OBJECTID",
    ),
    Layer(
        "city_gis_addresses",
        "DataPortal/DataPortal_BuildingsAddresses",
        0,  # Address Points Bloomington (subunits share a point; silver keeps one per address)
        (
            "objectid",
            "street_number",
            "street_direction",
            "street_name",
            "street_suffix",
            "lat",
            "lon",
        ),
        "objectid",
    ),
)


def pull(
    lake: Lake, run_id: str, bbox: tuple[float, float, float, float] = arcgis.CAMPUS_DOWNTOWN
) -> dict[str, tuple[bool, int]]:
    """Each layer inside the box: source -> (stored a new copy, features)."""
    found: dict[str, tuple[bool, int]] = {}
    for layer in LAYERS:
        body, url, page = arcgis.fetch_layer(
            layer.service, layer.layer, layer.fields, bbox, layer.order
        )
        stored = arcgis.store_if_changed(lake, layer.source, body, url, page, run_id)
        found[layer.source] = (stored, len(arcgis.features(body)))
    return found


def _provenance(manifest: bronze.Manifest) -> tuple[object, ...]:
    return (manifest.key, manifest.run_id, manifest.fetched_at.astimezone(UTC).replace(tzinfo=None))


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def street_rows(manifest: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
    found = []
    for feature in arcgis.features(body):
        props, shape = feature.get("properties") or {}, feature.get("geometry")
        name = str(props.get("fullname") or "").strip()
        if not name or not shape or shape.get("type") not in {"LineString", "MultiLineString"}:
            continue
        found.append(
            (
                _int(props.get("objectid")),
                name,
                street_key(name),
                _int(props.get("lowadd")),
                _int(props.get("highadd")),
                str(props.get("lowxst") or "").strip() or None,
                str(props.get("highxst") or "").strip() or None,
                json.dumps(shape, separators=(",", ":")),
                *_provenance(manifest),
            )
        )
    return found


def intersection_rows(manifest: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
    found = []
    for feature in arcgis.features(body):
        props, shape = feature.get("properties") or {}, feature.get("geometry") or {}
        name = str(props.get("intname") or "").strip()
        parts = [p.strip() for p in name.split("&")]
        coords = shape.get("coordinates") if shape.get("type") == "Point" else None
        if len(parts) != 2 or not all(parts) or not coords:
            continue
        found.append(
            (
                _int(props.get("OBJECTID")),
                name,
                street_key(parts[0]),
                street_key(parts[1]),
                round(float(coords[1]), 6),
                round(float(coords[0]), 6),
                *_provenance(manifest),
            )
        )
    return found


def address_rows(manifest: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
    """One row per street address: apartment subunits share their building's point."""
    seen: set[tuple[int, str, str]] = set()
    found = []
    for feature in arcgis.features(body):
        props = feature.get("properties") or {}
        number, name = _int(props.get("street_number")), str(props.get("street_name") or "")
        lat, lon = props.get("lat"), props.get("lon")
        if number is None or not name.strip() or lat is None or lon is None:
            continue
        direction = str(props.get("street_direction") or "").strip().upper()
        key = (number, direction, street_key(name))
        if key in seen:
            continue
        seen.add(key)
        found.append(
            (
                number,
                direction or None,
                key[2],
                round(float(lat), 6),
                round(float(lon), 6),
                *_provenance(manifest),
            )
        )
    return found


STAGED: dict[str, tuple[str, Columns, Any]] = {
    "geo_streets": ("city_gis_streets", STREETS, street_rows),
    "geo_intersections": ("city_gis_intersections", INTERSECTIONS, intersection_rows),
    "geo_addresses": ("city_gis_addresses", ADDRESSES, address_rows),
}
