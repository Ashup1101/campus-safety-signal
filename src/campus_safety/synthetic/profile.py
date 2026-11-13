"""Rate profiles the generator draws from: hour, weekday, month, category and location weights
and a yearly total, learned from real incidents in the warehouse (never from a single row) and
bounded by Clery totals where they exist. Locations are campus places and street segments only;
addresses are excluded so no synthetic row can carry a business.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from campus_safety.iu_crime_log.classify import Severity, is_sensitive, severity

LOCATION_TYPES = ("place", "street_segment", "block")
MIN_LOCATION_ROWS = 3  # a place seen fewer times than this is left out of the vocabulary
DUCKDB_CONFIG: dict[str, str | bool | int | float | list[str]] = {
    "memory_limit": "1GB",
    "threads": 2,
}

# Fallbacks when the warehouse has no real rows: a night-heavy day, weekend-heavy week, a
# term-time year, and a small campus vocabulary. Tests and empty lakes use these.
DEFAULT_HOURS = (
    4, 3, 3, 2, 1, 1, 1, 2, 3, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 6, 6, 5,
)  # fmt: skip
DEFAULT_WEEKDAYS = (4, 4, 4, 5, 6, 7, 5)  # Monday..Sunday
DEFAULT_MONTHS = (5, 6, 6, 6, 3, 2, 2, 5, 7, 7, 5, 3)
DEFAULT_CATEGORIES = {
    "ILLEGAL CONSUMPTION/POSSESSION OF ALCOHOL BY MINOR": 30,
    "THEFT - ALL OTHER": 20,
    "CRIMINAL MISCHIEF": 10,
    "POSSESSION OF MARIJUANA": 10,
    "BATTERY NO INJURY": 5,
    "BURGLARY": 3,
    "ROBBERY": 1,
    "POSSESSION OF HANDGUN WITHOUT LICENSE": 1,
}
DEFAULT_LOCATIONS = {
    "TETER QUAD": 10,
    "WRIGHT QUAD": 8,
    "FOREST QUAD": 8,
    "WELLS LIBRARY": 5,
    "10TH STREET/WEST OF EAGLESON": 4,
    "7TH STREET/WEST OF EAGLESON": 3,
    "3RD STREET/WEST OF EAGLESON": 3,
    "ATHLETIC/RED LOT": 2,
}
DEFAULT_YEARLY_TOTAL = 700


@dataclass(frozen=True)
class Profile:
    hours: tuple[float, ...]  # 24 weights
    weekdays: tuple[float, ...]  # 7, Monday first
    months: tuple[float, ...]  # 12
    categories: Mapping[str, float]  # offense label -> weight (never sensitive)
    locations: Mapping[str, float]  # location text -> weight
    yearly_total: float
    yearly_bounds: Mapping[int, float] = field(default_factory=dict)  # Clery totals per year
    origin: str = "default"

    def __post_init__(self) -> None:
        if (len(self.hours), len(self.weekdays), len(self.months)) != (24, 7, 12):
            raise ValueError("profile needs 24 hour, 7 weekday and 12 month weights")
        if not self.categories or not self.locations:
            raise ValueError("profile needs categories and locations")
        if any(is_sensitive(label) for label in self.categories):
            raise ValueError("profile categories must not be sensitive offenses")

    def total_for(self, year: int) -> float:
        return self.yearly_bounds.get(year, self.yearly_total)


def default() -> Profile:
    return Profile(
        DEFAULT_HOURS,
        DEFAULT_WEEKDAYS,
        DEFAULT_MONTHS,
        DEFAULT_CATEGORIES,
        DEFAULT_LOCATIONS,
        DEFAULT_YEARLY_TOTAL,
    )


def _weights(counts: Mapping[int, int], size: int, floor: float = 0.5) -> tuple[float, ...]:
    return tuple(float(counts.get(i, 0)) + floor for i in range(size))


def from_warehouse(warehouse: Path, lower: date, upper: date) -> Profile:
    """Profile learned from official, non-sensitive incidents outside the gap. Rows inside
    the gap would be synthetic from an earlier run, so they are never used."""
    import duckdb

    if not warehouse.exists():
        return default()
    with duckdb.connect(str(warehouse), read_only=True, config=DUCKDB_CONFIG) as con:
        rows = con.execute(
            "select hour(occurred_from), isodow(occurred_from), month(occurred_from),"
            " year(occurred_from), incident_type, location_text, location_type"
            " from silver.incidents where source = 'official' and not is_sensitive"
            " and occurred_from is not null and (occurred_from < $lower or occurred_from > $upper)"
            " and year(occurred_from) between 2000 and 2100",
            {"lower": lower, "upper": upper},
        ).fetchall()
        bounds = {
            int(year): float(total)
            for year, total in con.execute(
                "select calendar_year, sum(count) from silver.calibration_clery"
                " where location = 'On Campus' group by 1"
            ).fetchall()
        }
    if len(rows) < 100:
        return default()
    hours: dict[int, int] = {}
    weekdays: dict[int, int] = {}
    months: dict[int, int] = {}
    years: dict[int, int] = {}
    categories: dict[str, float] = {}
    locations: dict[str, float] = {}
    for hour, isodow, month, year, kind, location, kind_of_place in rows:
        hours[hour] = hours.get(hour, 0) + 1
        weekdays[isodow - 1] = weekdays.get(isodow - 1, 0) + 1
        months[month - 1] = months.get(month - 1, 0) + 1
        years[year] = years.get(year, 0) + 1
        if kind and severity(kind) is not Severity.UNCLASSIFIED and not is_sensitive(kind):
            categories[kind] = categories.get(kind, 0) + 1
        if location and kind_of_place in LOCATION_TYPES:
            locations[location] = locations.get(location, 0) + 1
    locations = {k: v for k, v in locations.items() if v >= MIN_LOCATION_ROWS}
    full_years = [n for year, n in years.items() if n >= 200]
    yearly = sum(full_years) / len(full_years) if full_years else DEFAULT_YEARLY_TOTAL
    return Profile(
        _weights(hours, 24),
        _weights(weekdays, 7),
        _weights(months, 12),
        categories or DEFAULT_CATEGORIES,
        locations or DEFAULT_LOCATIONS,
        yearly,
        bounds,
        origin="warehouse",
    )
