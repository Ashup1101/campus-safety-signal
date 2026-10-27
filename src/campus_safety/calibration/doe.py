"""U.S. Department of Education Campus Safety and Security data: the Clery statistics every
institution reports, one zip per survey year (each covering the three prior calendar years).

Only IU Bloomington's rows (UNITID 151351, all branches) are kept in silver.
"""

import io
import json
import re
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator, Sequence

import xlrd

from campus_safety import fetch
from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

SOURCE = "doe_campus_safety"
API = "https://ope.ed.gov/campussafety/api/dataFiles"
UNITID = "151351"
MAX_ZIP_BYTES = 120 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
DELAY_SECONDS = 2.0
# Oncampuscrime222324.xls: where, what, and the three calendar years covered.
_MEMBER = re.compile(
    r"^(oncampus|noncampus|publicproperty|reported|residencehall)"
    r"(crime|arrest|discipline|vawa)(\d{6})\.xls$",
    re.I,
)
_COUNT = re.compile(r"^([A-Z_]+?)(\d{2})$")

ROWS = (
    ("source_ref", "VARCHAR"),
    ("run_id", "VARCHAR"),
    ("survey_year", "INTEGER"),
    ("unitid_p", "VARCHAR"),
    ("branch", "VARCHAR"),
    ("location", "VARCHAR"),  # oncampus, noncampus, publicproperty, reported, residencehall
    ("category", "VARCHAR"),  # crime, arrest, discipline, vawa
    ("offense", "VARCHAR"),  # Clery code, e.g. BURGLA, RAPE, LIQUOR
    ("calendar_year", "INTEGER"),
    ("count", "INTEGER"),
)


def file_url(name: str) -> str:
    return f"{API}/file?fileName={name}"


def pull(
    lake: Lake,
    run_id: str,
    survey_years: Iterable[int],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    listing = fetch.polite_get(f"{API}/fileList")
    available = {item["FileName"] for item in json.loads(listing.body)}
    stored = 0
    for year in survey_years:
        name = f"Crime{year}EXCEL.zip"
        if name not in available:
            continue
        sleep(DELAY_SECONDS)
        page = fetch.polite_get(file_url(name), max_bytes=MAX_ZIP_BYTES)
        bronze.write(
            lake,
            source=SOURCE,
            body=page.body,
            url=file_url(name),
            fetched_at=page.fetched_at,
            http_status=page.status,
            run_id=f"{run_id}-{year}",
            ext="zip",
        )
        stored += 1
    return stored


def survey_year(manifest: bronze.Manifest) -> int:
    match = re.search(r"Crime(\d{4})EXCEL\.zip", manifest.url)
    if match is None:
        raise ValueError(f"{manifest.key}: not a Crime<year>EXCEL.zip download")
    return int(match[1])


def rows(manifest: bronze.Manifest, body: bytes) -> list[tuple[object, ...]]:
    year = survey_year(manifest)
    found: list[tuple[object, ...]] = []
    for location, category, header, data in _sheets(body):
        found += clery_rows(manifest, year, location, category, header, data)
    return found


def _sheets(body: bytes) -> Iterator[tuple[str, str, list[str], list[Sequence[object]]]]:
    """(location, category, header, IU rows) for each Clery sheet in a survey zip."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for member in archive.infolist():
            match = _MEMBER.match(member.filename.rsplit("/", 1)[-1])
            if match is None:
                continue
            if member.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"{member.filename}: larger than {MAX_MEMBER_BYTES} bytes")
            sheet = xlrd.open_workbook(file_contents=archive.read(member)).sheet_by_index(0)
            # 10k institutions per sheet: keep only IU's rows before building lists.
            data: list[Sequence[object]] = [
                sheet.row_values(r)
                for r in range(1, sheet.nrows)
                if _unitid(sheet.cell_value(r, 0)).startswith(UNITID)
            ]
            header = [str(cell) for cell in sheet.row_values(0)]
            yield match[1].lower(), match[2].lower(), header, data


def _unitid(value: object) -> str:
    return f"{value:.0f}" if isinstance(value, float) else str(value)


def clery_rows(
    manifest: bronze.Manifest,
    year: int,
    location: str,
    category: str,
    header: list[str],
    data: list[Sequence[object]],
) -> list[tuple[object, ...]]:
    unit, branch = header.index("UNITID_P"), header.index("BRANCH")
    counts = [
        (index, m[1], 2000 + int(m[2]))
        for index, m in ((i, _COUNT.match(name)) for i, name in enumerate(header))
        if m and not m[1].startswith("FILTER")
    ]
    return [
        (
            manifest.key,
            manifest.run_id,
            year,
            _unitid(values[unit]),
            str(values[branch]).strip(),
            location,
            category,
            offense,
            calendar_year,
            int(float(str(values[index]))),
        )
        for values in data
        if _unitid(values[unit]).startswith(UNITID)
        for index, offense, calendar_year in counts
        if values[index] not in ("", None)
    ]
