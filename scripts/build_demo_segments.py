"""Build apps/server/demo_server/segments.geojson: the demo's hand-picked street segments.

Geometry comes from the City of Bloomington road centerlines (public GIS; fetched politely once and
cached under data/demo/sources/). Each segment lists the location phrases the IU crime log uses for
it, so incidents match without geocoding. Run: `uv run python scripts/build_demo_segments.py`.
"""

import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from campus_safety import fetch

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "demo" / "sources" / "road_centerlines.geojson"
OUT = ROOT / "apps" / "server" / "demo_server" / "segments.geojson"
CENTERLINES = (
    "https://bloomington.in.gov/arcgis-server/rest/services/DataPortal/"
    "DataPortal_Transportation/MapServer/4/query"
)
BBOX = "-86.540,39.158,-86.505,39.178"
ATTRIBUTION = "Street geometry: City of Bloomington GIS road centerlines"

_SEP = r"\s*(@|&|AND|/)\s*"


def _kirkwood(block: int, west: str, east: str) -> dict[str, Any]:
    cross = f"({west}|{east})"
    return {
        "id": f"kirkwood_{block}",
        "name": f"E Kirkwood Ave, {block} block ({west.title()} to {east.title()})",
        "street": "E Kirkwood AVE",
        "blocks": [block],
        "match": [
            rf"(^|[-,]\s*){block // 100}\d\d\s+(BLK\s+|BLOCK\s+)?E\.?\s+KIRKWOOD",
            rf"KIRKWOOD{_SEP}{cross}\b",
            rf"\b{cross}\s*(ST\.?|STREET|AVE\.?|AVENUE)?{_SEP}KIRKWOOD",
        ],
    }


def _campus(sid: str, name: str, street: str, blocks: list[int], phrase: str) -> dict[str, Any]:
    return {"id": sid, "name": name, "street": street, "blocks": blocks, "match": [phrase]}


SEGMENTS = [
    _kirkwood(100, "WALNUT", "WASHINGTON"),
    _kirkwood(200, "WASHINGTON", "LINCOLN"),
    _kirkwood(300, "LINCOLN", "GRANT"),
    _kirkwood(400, "GRANT", "DUNN"),
    _kirkwood(500, "DUNN", "INDIANA"),
    _campus(
        "e3rd_west_eagleson",
        "E 3rd St, Indiana Ave to Eagleson Ave",
        "E 3rd ST",
        [600, 800, 900, 1000, 1110, 1200, 1300],
        r"\b3RD (STREET|ST\.?)\s*/\s*WEST OF EAGLESON",
    ),
    _campus(
        "e3rd_east_eagleson",
        "E 3rd St, Eagleson Ave to Union St",
        "E 3rd ST",
        [1400, 1500, 1600, 1700, 1800, 1900, 1991],
        r"\b3RD (STREET|ST\.?)\s*/\s*EAST OF EAGLESON",
    ),
    _campus(
        "e7th_west_eagleson",
        "E 7th St, Indiana Ave to Eagleson Ave",
        "E 7th ST",
        [600, 700, 800, 900, 1000, 1140, 1300],
        r"\b7TH (STREET|ST\.?)\s*/\s*WEST OF EAGLESON",
    ),
    _campus(
        "e7th_east_eagleson",
        "E 7th St, Eagleson Ave to Union St",
        "E 7th ST",
        [1500, 1600, 1800, 1900],
        r"\b7TH (STREET|ST\.?)\s*/\s*EAST OF EAGLESON",
    ),
    _campus(
        "e10th_west_eagleson",
        "E 10th St, Indiana Ave to Eagleson Ave",
        "E 10th ST",
        [600, 700, 800, 900, 1000, 1200, 1300],
        r"\b1[0O]TH (STREET|ST\.?)\s*/\s*WEST OF EAGLESON",
    ),
    _campus(
        "e10th_east_eagleson",
        "E 10th St, Eagleson Ave to Union St",
        "E 10th ST",
        [1500, 1600, 1800],
        r"\b1[0O]TH (STREET|ST\.?)\s*/\s*EAST OF EAGLESON",
    ),
    _campus(
        "dunn_south_10th",
        "N Dunn St, Kirkwood Ave to 10th St",
        "N Dunn ST",
        [100, 200, 300, 400, 500],
        r"\bDUNN (STREET|ST\.?)\s*/\s*SOUTH OF 1[0O]TH",
    ),
    _campus(
        "indiana_south_10th",
        "N Indiana Ave, Kirkwood Ave to 10th St",
        "N Indiana AVE",
        [100, 200, 300, 400, 500],
        r"\bINDIANA (AVENUE|AVE\.?)\s*/\s*SOUTH OF 1[0O]TH",
    ),
]


def centerlines() -> dict[str, Any]:
    if not CACHE.exists():
        params = {
            "where": "1=1",
            "geometry": BBOX,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "fullname,addblock,lowxst,highxst",
            "outSR": "4326",
            "f": "geojson",
        }
        page = fetch.polite_get(f"{CENTERLINES}?{urllib.parse.urlencode(params)}", timeout=60)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(page.body)
    data: dict[str, Any] = json.loads(CACHE.read_text())
    return data


def build(lines: dict[str, Any]) -> dict[str, Any]:
    by_block: dict[tuple[str, int], list[list[list[float]]]] = {}
    for feature in lines["features"]:
        props, geometry = feature["properties"], feature["geometry"]
        block = str(props.get("addblock") or "").strip()
        if geometry is None or geometry["type"] != "LineString" or not block.isdigit():
            continue
        key = (props["fullname"], int(block))
        coords = [[round(x, 6), round(y, 6)] for x, y in geometry["coordinates"]]
        by_block.setdefault(key, []).append(coords)
    features = []
    for spec in SEGMENTS:
        parts = [part for block in spec["blocks"] for part in by_block[(spec["street"], block)]]
        features.append(
            {
                "type": "Feature",
                "id": spec["id"],
                "properties": {"id": spec["id"], "name": spec["name"], "match": spec["match"]},
                "geometry": {"type": "MultiLineString", "coordinates": parts},
            }
        )
    return {
        "type": "FeatureCollection",
        "attribution": ATTRIBUTION,
        "note": "Demo data: hand-picked segments for the Kirkwood corridor and campus core.",
        "features": features,
    }


def main() -> int:
    OUT.write_text(json.dumps(build(centerlines()), indent=1) + "\n")
    print(f"wrote {len(SEGMENTS)} segments to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
