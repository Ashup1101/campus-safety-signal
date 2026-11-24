"""The city's street network for campus and downtown: road centerlines (names, address ranges,
cross streets), named intersections, and address points. Public City of Bloomington GIS layers,
read politely (geo.arcgis) and stored in bronze only when they change. Incidents are placed on
these in later steps; nothing here touches incident data."""

from dataclasses import dataclass

from campus_safety.geo import arcgis
from campus_safety.lake.storage import Lake


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
