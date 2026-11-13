"""Phone location traces with expected bands, for testing the inside / nearby / away logic
the phone computes against a watch zone. Entirely synthetic: fictitious walkers around the
demo's street segments. Written under data/synthetic/, never into the lake.
"""

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from campus_safety.lake.parquet import Columns, write_parquet

EARTH_M = 6_371_000.0
NEARBY_FACTOR = 3.0  # nearby = within 3 radii of the zone center
STEP_SECONDS = 30
WALK_M_PER_S = 1.4

COLUMNS: Columns = (
    ("seed", "BIGINT"),
    ("walker", "INTEGER"),
    ("at", "TIMESTAMP"),
    ("lat", "DOUBLE"),
    ("lon", "DOUBLE"),
    ("zone_lat", "DOUBLE"),
    ("zone_lon", "DOUBLE"),
    ("zone_radius_m", "DOUBLE"),
    ("distance_m", "DOUBLE"),
    ("expected_band", "VARCHAR"),  # inside | nearby | away
)


@dataclass(frozen=True)
class Zone:
    lat: float
    lon: float
    radius_m: float


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def band(distance: float, zone: Zone) -> str:
    if distance <= zone.radius_m:
        return "inside"
    if distance <= zone.radius_m * NEARBY_FACTOR:
        return "nearby"
    return "away"


def walk(
    seed: int, walkers: int, zone: Zone, start: datetime, steps: int = 240
) -> list[tuple[object, ...]]:
    """Each walker starts far out, drifts toward the zone, crosses it, and leaves."""
    rng = random.Random(f"traces|{seed}")  # noqa: S311 (simulation, not security)
    rows: list[tuple[object, ...]] = []
    for walker in range(1, walkers + 1):
        heading = rng.uniform(0, 2 * math.pi)
        reach = zone.radius_m * NEARBY_FACTOR * 2
        lat = zone.lat + (reach * math.cos(heading)) / EARTH_M * (180 / math.pi)
        lon = zone.lon + (reach * math.sin(heading)) / (
            EARTH_M * math.cos(math.radians(zone.lat))
        ) * (180 / math.pi)
        d_lat = (zone.lat - lat) / (steps / 2)
        d_lon = (zone.lon - lon) / (steps / 2)
        at = start
        for _ in range(steps):
            jitter = rng.uniform(-0.2, 0.2)
            lat += d_lat * (1 + jitter)
            lon += d_lon * (1 + jitter)
            distance = distance_m(lat, lon, zone.lat, zone.lon)
            rows.append(
                (
                    seed,
                    walker,
                    at,
                    lat,
                    lon,
                    zone.lat,
                    zone.lon,
                    zone.radius_m,
                    distance,
                    band(distance, zone),
                )
            )
            at += timedelta(seconds=STEP_SECONDS)
    return rows


def save(rows: list[tuple[object, ...]], path: Path) -> None:
    write_parquet(path, COLUMNS, rows)
