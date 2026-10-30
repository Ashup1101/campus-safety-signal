"""U.S. Department of Education Campus Safety and Security data: the Clery statistics every
institution reports, one zip per survey year (each covering the three prior calendar years).

Never fetched: ope.ed.gov's robots.txt answers our crawler with 403, which we treat as a ban. The
owner downloads CrimeYYYYEXCEL.zip in a browser into data/manual/doe/, and `calibration import-doe`
copies those files into bronze with their sha256. Only IU Bloomington's rows (UNITID 151351, all
branches) are kept in silver.
"""

import hashlib
import io
import re
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import xlrd

from campus_safety.lake import bronze
from campus_safety.lake.storage import Lake

SOURCE = "doe_campus_safety"
MANUAL_DIR = Path("manual", "doe")  # under the data dir; filled by hand
UNITID = "151351"
MAX_ZIP_BYTES = 120 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
_ZIP_NAME = re.compile(r"^Crime(\d{4})EXCEL\.zip$")
# Oncampuscrime222324.xls: where, what, and the three calendar years covered.
_MEMBER = re.compile(
    r"^(oncampus|noncampus|publicproperty|reported|residencehall)"
    r"(crime|arrest|discipline|vawa)(\d{6})\.xls$",
    re.I,
)
_COUNT = re.compile(r"^([A-Z_]+?)(\d{2})$")

ROWS = (
    ("source_ref", "VARCHAR"),
    ("source_sha256", "VARCHAR"),  # of the zip as downloaded
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


@dataclass(frozen=True)
class ImportSummary:
    imported: int
    present: int  # same bytes already in bronze
    skipped: int  # not CrimeYYYYEXCEL.zip, too large, or not a zip


def import_manual(lake: Lake, data_dir: Path) -> ImportSummary:
    """Copy hand-downloaded survey zips from <data_dir>/manual/doe/ into bronze. No network."""
    folder = data_dir / MANUAL_DIR
    known = {manifest.sha256 for manifest in bronze.manifests(lake, SOURCE)}
    imported = present = skipped = 0
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if (
            not path.is_file()
            or not _ZIP_NAME.match(path.name)
            or path.stat().st_size > MAX_ZIP_BYTES
            or not zipfile.is_zipfile(path)
        ):
            skipped += 1
            continue
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest in known:
            present += 1
            continue
        bronze.write(
            lake,
            source=SOURCE,
            body=body,
            url=f"manual:{MANUAL_DIR.as_posix()}/{path.name}",
            fetched_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),  # when it was downloaded
            http_status=None,
            run_id=f"manual-{digest[:12]}",
            ext="zip",
        )
        known.add(digest)
        imported += 1
    return ImportSummary(imported, present, skipped)


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
            manifest.sha256,
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
