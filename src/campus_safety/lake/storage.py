"""Object storage behind LAKE_URI: file:// for local work and tests, s3:// for the real lake.

Keys are relative to the lake root, e.g. "bronze/iu_crime_log/ingest_date=2026-10-26/<file>".
`create` is write-once (bronze); `put` may replace an object (silver, gold, private notes).
"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import unquote, urlsplit

from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client


class ObjectExistsError(FileExistsError):
    """A write-once `create` found the key already present."""


class LakeConfigError(ValueError):
    pass


class Lake(Protocol):
    uri: str

    def create(self, key: str, body: bytes) -> None: ...

    def put(self, key: str, body: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def keys(self, prefix: str) -> list[str]: ...


class FileLake:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.uri = self.root.as_uri()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"key escapes the lake root: {key!r}")
        return path

    def create(self, key: str, body: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".partial-")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(body)
            # link() is atomic and refuses an existing target: the file:// If-None-Match: *.
            os.link(tmp, path)
        except FileExistsError as e:
            raise ObjectExistsError(key) from e
        finally:
            os.unlink(tmp)

    def put(self, key: str, body: bytes) -> None:
        path = self._path(key)
        if path.exists() and path.read_bytes() == body:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".partial-")
        with os.fdopen(fd, "wb") as file:
            file.write(body)
        os.replace(tmp, path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def keys(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.is_dir():
            return []
        found = (p for p in base.rglob("*") if p.is_file() and not p.name.startswith(".partial-"))
        return sorted(p.relative_to(self.root).as_posix() for p in found)


class S3Lake:
    def __init__(self, bucket: str, prefix: str, client: "S3Client | None" = None) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.uri = f"s3://{bucket}/{self.prefix}" if self.prefix else f"s3://{bucket}"
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._s3 = client

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def create(self, key: str, body: bytes) -> None:
        try:
            self._s3.put_object(Bucket=self.bucket, Key=self._key(key), Body=body, IfNoneMatch="*")
        except ClientError as e:
            # 412 when the key exists; 409 when a concurrent conditional write won the race.
            if e.response.get("Error", {}).get("Code") in (
                "PreconditionFailed",
                "ConditionalRequestConflict",
            ):
                raise ObjectExistsError(key) from e
            raise

    def put(self, key: str, body: bytes) -> None:
        # A single-part upload's ETag is the MD5 of its body: skip re-uploading identical bytes.
        try:
            head = self._s3.head_object(Bucket=self.bucket, Key=self._key(key))
            if head["ETag"].strip('"') == hashlib.md5(body, usedforsecurity=False).hexdigest():
                return
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        self._s3.put_object(Bucket=self.bucket, Key=self._key(key), Body=body)

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()

    def keys(self, prefix: str) -> list[str]:
        root = f"{self.prefix}/" if self.prefix else ""
        pages = self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self._key(prefix)
        )
        return sorted(
            item["Key"].removeprefix(root) for page in pages for item in page.get("Contents", [])
        )


class CachedLake:
    """Reads immutable objects (bronze) through a local cache; everything else goes direct."""

    def __init__(self, lake: Lake, cache_dir: Path) -> None:
        self._lake = lake
        self._cache = FileLake(cache_dir)
        self.uri = lake.uri

    def create(self, key: str, body: bytes) -> None:
        self._lake.create(key, body)

    def put(self, key: str, body: bytes) -> None:
        self._lake.put(key, body)

    def get(self, key: str) -> bytes:
        try:
            return self._cache.get(key)
        except FileNotFoundError:
            body = self._lake.get(key)
            self._cache.put(key, body)
            return body

    def keys(self, prefix: str) -> list[str]:
        return self._lake.keys(prefix)


def open_lake(uri: str | None, cache_dir: Path | None = None) -> Lake:
    if not uri:
        raise LakeConfigError("LAKE_URI is not set (file:///abs/path or s3://bucket/prefix)")
    parts = urlsplit(uri)
    if parts.scheme == "file" and not parts.netloc:
        return FileLake(Path(unquote(parts.path)))
    if parts.scheme == "s3" and parts.netloc:
        lake = S3Lake(parts.netloc, parts.path)
        return CachedLake(lake, cache_dir) if cache_dir is not None else lake
    raise LakeConfigError(f"LAKE_URI must be file:///abs/path or s3://bucket/prefix, got {uri!r}")
