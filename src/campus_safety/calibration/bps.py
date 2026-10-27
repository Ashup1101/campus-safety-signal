"""City of Bloomington Board of Public Safety: the police department's monthly statistics
slides inside each meeting packet.

Packets are stored raw in bronze. They also hold minutes that name people, so silver keeps only
the numbers matched below: year-to-date calls for service and the change on the prior year,
year-to-date traffic stops per year, and incidents involving weapons, firearms, and shots fired
at a person.
"""

import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime

from campus_safety import fetch, pdf
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

SOURCE = "city_bps_packets"
MEETINGS = "https://bloomington.in.gov/onboard/committees/25/meetings"
DELAY_SECONDS = 2.5  # the site's robots.txt asks for a 2 s crawl delay
MAX_PACKET_BYTES = 80 * 1024 * 1024
MAX_PACKET_PAGES = 400
_PACKET = re.compile(
    r"<strong>Packet:</strong>\s*<a[^>]*href=\"(https://bloomington\.in\.gov/onboard/meetingFiles/"
    r"(\d+)/download)\"",
)

ROWS = (
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("metric", "VARCHAR"),
    ("period_year", "INTEGER"),  # the year-to-date period the slide reports
    ("period_month", "INTEGER"),
    ("stat_year", "INTEGER"),  # the year the value is for (traffic stops list three years)
    ("value", "INTEGER"),
)

_CALLS = re.compile(r"responded to ([\d,]+) calls for service through (\w+) of (\d{4})", re.I)
_CHANGE = re.compile(r"(increase|decrease) of ([\d,]+) calls from the same period in (\d{4})", re.I)
_STOPS = re.compile(r"TRAFFIC STOP COMPARISON(.{0,160}?)(?=[A-Z]{4,} [A-Z]{4,}|$)")
_STOP_YEAR = re.compile(r"\b(20\d{2}) ([\d,]+)\b")
_WEAPONS = re.compile(r"So far in (\d{4}), there have been ([\d,]+) incidents where weapons", re.I)
_FIREARMS = re.compile(r"firearm has been reported in ([\d,]+) incidents", re.I)
_FIRED = re.compile(r"fired at a person in ([\d,]+)", re.I)


def packet_links(html: str) -> list[tuple[str, str]]:
    """(download URL, meeting file id) for every packet listed on a meetings page."""
    return _PACKET.findall(html)


def pull(
    lake: Lake,
    run_id: str,
    years: Iterable[int],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    done = {manifest.url for manifest in bronze.manifests(lake, SOURCE)}
    stored = 0
    for year in years:
        listing = fetch.polite_get(f"{MEETINGS}?year={year}")
        sleep(DELAY_SECONDS)
        for url, file_id in packet_links(listing.body.decode("utf-8", errors="replace")):
            if url in done:
                continue
            page = fetch.polite_get(url, max_bytes=MAX_PACKET_BYTES)
            bronze.write(
                lake,
                source=SOURCE,
                body=page.body,
                url=url,
                fetched_at=page.fetched_at,
                http_status=page.status,
                run_id=f"{run_id}-{file_id}",
                ext="pdf",
            )
            done.add(url)
            stored += 1
            sleep(DELAY_SECONDS)
    return stored


def _number(text: str) -> int:
    return int(text.replace(",", ""))


def metrics(text: str) -> list[tuple[str, int, int, int, int]]:
    """(metric, period_year, period_month, stat_year, value) found in a packet's text."""
    flat = " ".join(text.split())
    calls = _CALLS.search(flat)
    if calls is None:
        return []  # no statistics slide (special sessions, or a new layout)
    year, month = int(calls[3]), datetime.strptime(calls[2], "%B").month
    found = [("calls_for_service_ytd", year, month, year, _number(calls[1]))]
    change = _CHANGE.search(flat)
    if change:
        sign = 1 if change[1].lower() == "increase" else -1
        found.append(("calls_for_service_change_ytd", year, month, year, sign * _number(change[2])))
    stops = _STOPS.search(flat)
    if stops:
        found += [
            ("traffic_stops_ytd", year, month, int(stop_year), _number(value))
            for stop_year, value in _STOP_YEAR.findall(stops[1])
        ]
    weapons = _WEAPONS.search(flat)
    if weapons:
        found.append(("weapon_incidents_ytd", year, month, int(weapons[1]), _number(weapons[2])))
    for pattern, metric in ((_FIREARMS, "firearm_incidents_ytd"), (_FIRED, "shots_at_person_ytd")):
        match = pattern.search(flat)
        if match:
            found.append((metric, year, month, year, _number(match[1])))
    return found


def rows(manifest: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
    text = pdf.extract_text(body, MAX_PACKET_PAGES)
    return [(manifest.key, manifest.run_id, *metric) for metric in metrics(text)]
