"""Bronze: raw responses exactly as fetched, gzipped, each with a JSON manifest. Write once.

Key: bronze/<source>/ingest_date=YYYY-MM-DD/<UTC stamp>_<run_id>.<ext>.gz, manifest beside it
as <UTC stamp>_<run_id>.manifest.json. The run id makes every key unique, and every write is
create-only, so nothing in bronze is ever replaced.
"""

import gzip
import hashlib
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from campus_safety.lake.storage import Lake

_STAMP = "%Y%m%dT%H%M%SZ"
_RUN_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_MANIFEST = ".manifest.json"


class BronzeIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    source: str
    key: str  # the raw object, relative to the lake root
    url: str
    fetched_at: datetime  # UTC
    sha256: str  # of the uncompressed body
    http_status: int
    run_id: str
    captured_at: datetime | None = None  # archive sources: when the archive saw the page

    @property
    def observed_at(self) -> datetime:
        """When the content was live: the archive capture time, else our fetch time."""
        return self.captured_at or self.fetched_at

    def to_json(self) -> bytes:
        fields = {
            **asdict(self),
            "fetched_at": self.fetched_at.isoformat(),
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
        }
        return json.dumps(fields, indent=2, sort_keys=True).encode()

    @classmethod
    def from_json(cls, data: bytes) -> "Manifest":
        fields = json.loads(data)
        captured = fields.get("captured_at")
        return cls(
            **{
                **fields,
                "fetched_at": datetime.fromisoformat(fields["fetched_at"]),
                "captured_at": datetime.fromisoformat(captured) if captured else None,
            }
        )


def new_run_id() -> str:
    """RUN_ID from the environment (CI sets gha-<run>-<attempt>), else a random local id."""
    run_id = os.environ.get("RUN_ID") or f"local-{secrets.token_hex(4)}"
    if not _RUN_ID.match(run_id):
        raise ValueError(f"run id must match {_RUN_ID.pattern}: {run_id!r}")
    return run_id


def raw_key(source: str, fetched_at: datetime, run_id: str, ext: str) -> str:
    at = fetched_at.astimezone(UTC)
    return f"bronze/{source}/ingest_date={at:%Y-%m-%d}/{at:{_STAMP}}_{run_id}.{ext}.gz"


def manifest_key(key: str) -> str:
    folder, _, name = key.rpartition("/")
    return f"{folder}/{name.split('.', 1)[0]}{_MANIFEST}"


def write(
    lake: Lake,
    *,
    source: str,
    body: bytes,
    url: str,
    fetched_at: datetime,
    http_status: int,
    run_id: str,
    ext: str,
    captured_at: datetime | None = None,
) -> Manifest:
    if not _RUN_ID.match(run_id):
        raise ValueError(f"run id must match {_RUN_ID.pattern}: {run_id!r}")
    key = raw_key(source, fetched_at, run_id, ext)
    manifest = Manifest(
        source=source,
        key=key,
        url=url,
        fetched_at=fetched_at.astimezone(UTC),
        sha256=hashlib.sha256(body).hexdigest(),
        http_status=http_status,
        run_id=run_id,
        captured_at=captured_at.astimezone(UTC) if captured_at else None,
    )
    lake.create(key, gzip.compress(body, mtime=0))
    lake.create(manifest_key(key), manifest.to_json())
    return manifest


def manifests(lake: Lake, source: str) -> list[Manifest]:
    """Every manifest for a source, oldest first. A raw object without one is ignored."""
    found = [
        Manifest.from_json(lake.get(key))
        for key in lake.keys(f"bronze/{source}/")
        if key.endswith(_MANIFEST)
    ]
    return sorted(found, key=lambda m: (m.fetched_at, m.key))


def read(lake: Lake, manifest: Manifest) -> bytes:
    body = gzip.decompress(lake.get(manifest.key))
    if hashlib.sha256(body).hexdigest() != manifest.sha256:
        raise BronzeIntegrityError(f"{manifest.key} does not match its manifest sha256")
    return body


def latest_fetch(lake: Lake, source: str) -> datetime | None:
    stamps = [
        key.rsplit("/", 1)[1].split("_", 1)[0]
        for key in lake.keys(f"bronze/{source}/")
        if key.endswith(_MANIFEST)
    ]
    if not stamps:
        return None
    return datetime.strptime(max(stamps), _STAMP).replace(tzinfo=UTC)
