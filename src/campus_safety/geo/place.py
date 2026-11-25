"""IUPD location strings on the city's street network, at the most precise level the text
supports, with that level kept as the precision. A street stretch ("10TH STREET/EAST OF JORDAN")
is the centerline piece of the street that starts at the named corner and runs to the next
corner on the named side. Anything unclear stays unplaced: a location is never guessed."""

import itertools
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from campus_safety.geo.normalize import (
    ALIASES,
    parse_address,
    parse_block,
    parse_segment,
    street_key,
)
from campus_safety.lake.parquet import Columns

Point = tuple[float, float]  # lon, lat (GeoJSON order)
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(39.17))  # at Bloomington
CORNER_M = 30.0  # a piece's end this close to the cross street is the corner
MIN_ALONG_M = 10.0  # the stretch must run at least this far to the named side
SAME_CORNER_M = 100.0  # candidates farther apart mean the streets meet twice: unclear
MAX_BLOCK_M = 400.0  # a hundred block whose address points spread farther is unclear
NEAR_PIECE_M = 50.0  # an address or block counts on its street's piece this close (for levels)

COLUMNS: Columns = (
    ("location_text", "VARCHAR"),
    ("location_type", "VARCHAR"),
    ("precision", "VARCHAR"),  # segment | address | block
    ("lat", "DOUBLE"),
    ("lon", "DOUBLE"),
    ("street_objectid", "BIGINT"),  # the centerline piece, for segment placements
    ("zonecode", "VARCHAR"),  # the police reporting zone holding the point, when known
    ("source_ref", "VARCHAR"),  # the city layer the coordinates come from
    ("run_id", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
)


@dataclass(frozen=True)
class Piece:
    objectid: int
    street: str  # street key
    low: str | None  # street key of the cross street at the low-address end
    high: str | None
    lowadd: int | None
    highadd: int | None
    lines: tuple[tuple[Point, ...], ...]

    @property
    def ends(self) -> tuple[Point, Point]:
        return self.lines[0][0], self.lines[-1][-1]


@dataclass(frozen=True)
class AddressPoint:
    number: int
    direction: str | None
    street: str  # street key
    lat: float
    lon: float


@dataclass(frozen=True)
class Placement:
    precision: str
    lat: float
    lon: float
    street_objectid: int | None


Provenance = tuple[str | None, str | None, datetime | None]


class Network:
    def __init__(
        self,
        pieces: Iterable[Piece],
        addresses: Iterable[AddressPoint],
        streets_from: Provenance = (None, None, None),
        addresses_from: Provenance = (None, None, None),
    ) -> None:
        self.pieces = tuple(pieces)
        self.streets_from, self.addresses_from = streets_from, addresses_from
        self.by_street: dict[str, list[Piece]] = {}
        for p in self.pieces:
            self.by_street.setdefault(p.street, []).append(p)
        self.known = set(self.by_street)
        self.by_address: dict[tuple[int, str], list[AddressPoint]] = {}
        for a in addresses:
            self.by_address.setdefault((a.number, a.street), []).append(a)
        self.address_streets = {street for _, street in self.by_address}

    @classmethod
    def from_rows(
        cls, streets: Sequence[Mapping[str, Any]], addresses: Sequence[Mapping[str, Any]] = ()
    ) -> "Network":
        """From silver.geo_streets- and geo_addresses-shaped rows (staged by geo.streets)."""
        pieces = [
            Piece(
                int(r["objectid"]),
                str(r["street_key"]),
                _cross(r["lowxst"]),
                _cross(r["highxst"]),
                r["lowadd"],
                r["highadd"],
                _lines(json.loads(r["geometry"])),
            )
            for r in streets
        ]
        points = [
            AddressPoint(
                int(r["street_number"]),
                r["street_direction"],
                str(r["street_key"]),
                float(r["lat"]),
                float(r["lon"]),
            )
            for r in addresses
        ]
        return cls(pieces, points, _provenance(streets), _provenance(addresses))

    def vertices(self, street: str) -> list[Point]:
        return [pt for p in self.by_street.get(street, []) for line in p.lines for pt in line]


def _provenance(rows: Sequence[Mapping[str, Any]]) -> Provenance:
    first = rows[0] if rows else {}
    return first.get("source_ref"), first.get("run_id"), first.get("ingested_at")


def _cross(name: str | None) -> str | None:
    key = street_key(name) if name else ""
    return ALIASES.get(key, key) or None


def _lines(shape: Mapping[str, Any]) -> tuple[tuple[Point, ...], ...]:
    raw = [shape["coordinates"]] if shape["type"] == "LineString" else shape["coordinates"]
    return tuple(tuple((float(x), float(y)) for x, y, *_ in line) for line in raw)


def _meters(a: Point, b: Point) -> float:
    return math.hypot((a[0] - b[0]) * M_PER_DEG_LON, (a[1] - b[1]) * M_PER_DEG_LAT)


def midpoint(lines: tuple[tuple[Point, ...], ...]) -> Point:
    """The point halfway along the piece."""
    steps = [(a, b, _meters(a, b)) for line in lines for a, b in itertools.pairwise(line)]
    remaining = sum(length for *_, length in steps) / 2
    for a, b, length in steps:
        if remaining <= length and length > 0:
            t = remaining / length
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        remaining -= length
    return lines[0][0]


def distance_to_lines(point: Point, lines: tuple[tuple[Point, ...], ...]) -> float:
    """Meters from point to the nearest spot on the lines."""
    best = math.inf
    for line in lines:
        for a, b in itertools.pairwise(line):
            ax, ay = (a[0] - point[0]) * M_PER_DEG_LON, (a[1] - point[1]) * M_PER_DEG_LAT
            bx, by = (b[0] - point[0]) * M_PER_DEG_LON, (b[1] - point[1]) * M_PER_DEG_LAT
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / span))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def _on_street(network: Network, street: str, lat: float, lon: float) -> int | None:
    """The street's centerline piece nearest to a point, when it is close enough."""
    pieces = network.by_street.get(street, [])
    near = [(distance_to_lines((lon, lat), p.lines), p.objectid) for p in pieces]
    best = min(near, default=None)
    return best[1] if best and best[0] <= NEAR_PIECE_M else None


def _toward(side: str, corner: Point, point: Point) -> float:
    """How far point lies from corner toward the named side, in meters (negative: other side)."""
    dx, dy = (point[0] - corner[0]) * M_PER_DEG_LON, (point[1] - corner[1]) * M_PER_DEG_LAT
    return {"east": dx, "west": -dx, "north": dy, "south": -dy}[side]


def place_segment(text: str, network: Network) -> Placement | None:
    segment = parse_segment(text, network.known)
    if segment is None:
        return None
    cross = network.vertices(segment.cross)
    found: list[tuple[float, int, Point, Point]] = []  # (along, objectid, corner, middle)
    for piece in network.by_street.get(segment.street, []):
        if segment.cross not in (piece.low, piece.high) or not cross:
            continue
        corner = min(piece.ends, key=lambda end: min(_meters(end, c) for c in cross))
        if min(_meters(corner, c) for c in cross) > CORNER_M:
            continue
        middle = midpoint(piece.lines)
        along = _toward(segment.side, corner, middle)
        if along >= MIN_ALONG_M:
            found.append((along, piece.objectid, corner, middle))
    if not found or any(_meters(found[0][2], f[2]) > SAME_CORNER_M for f in found):
        return None
    _, objectid, _, (lon, lat) = max(found, key=lambda f: (f[0], -f[1]))
    return Placement("segment", round(lat, 6), round(lon, 6), objectid)


def place_address(text: str, network: Network) -> Placement | None:
    """The city's address point for number + street (+ direction when given); two possible
    points (East and West 502) without a direction leave it unplaced."""
    address = parse_address(text, network.address_streets)
    if address is None:
        return None
    points = {
        (p.lat, p.lon)
        for p in network.by_address.get((address.number, address.street), [])
        if address.direction is None or p.direction in (None, address.direction)
    }
    if len(points) != 1:
        return None
    lat, lon = points.pop()
    return Placement("address", lat, lon, _on_street(network, address.street, lat, lon))


def place_block(text: str, network: Network) -> Placement | None:
    """The middle of the extent of the address points numbered in the hundred block on that
    street (and side, when given)."""
    block = parse_block(text, network.address_streets)
    if block is None:
        return None
    points = [
        p
        for number in range(block.number, block.number + 100)
        for p in network.by_address.get((number, block.street), [])
        if block.direction is None or p.direction in (None, block.direction)
    ]
    if not points or len({p.direction for p in points}) > 1:
        return None
    south, north = min(p.lat for p in points), max(p.lat for p in points)
    west, east = min(p.lon for p in points), max(p.lon for p in points)
    if _meters((west, south), (east, north)) > MAX_BLOCK_M:
        return None
    lat, lon = round((south + north) / 2, 6), round((west + east) / 2, 6)
    return Placement("block", lat, lon, _on_street(network, block.street, lat, lon))


PLACERS = {"street_segment": place_segment, "address": place_address, "block": place_block}


def rows(
    locations: Iterable[tuple[str, str]],
    network: Network,
    zone_of: Callable[[float, float], str | None] = lambda lon, lat: None,
) -> list[tuple[object, ...]]:
    """One row per placed (location_text, location_type); unplaced locations have no row.
    zone_of(lon, lat) names the police reporting zone holding the point."""
    found: list[tuple[object, ...]] = []
    for text, kind in sorted(set(locations)):
        placer = PLACERS.get(kind)
        placed = placer(text, network) if placer else None
        if placed:
            found.append(
                (
                    text,
                    kind,
                    placed.precision,
                    placed.lat,
                    placed.lon,
                    placed.street_objectid,
                    zone_of(placed.lon, placed.lat),
                    *(
                        network.streets_from
                        if placed.precision == "segment"
                        else network.addresses_from
                    ),
                )
            )
    return found
