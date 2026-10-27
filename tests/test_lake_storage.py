import gzip
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from campus_safety.lake import bronze
from campus_safety.lake.storage import (
    CachedLake,
    FileLake,
    Lake,
    LakeConfigError,
    ObjectExistsError,
    S3Lake,
    open_lake,
)

FETCHED = datetime(2026, 10, 26, 20, 46, 23, tzinfo=UTC)
URL = "https://protect.example.edu/crime-log/daily-logs.html"


@pytest.fixture
def s3_lake(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Lake]:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="lake-test")
        yield S3Lake("lake-test", "lake", client)


@pytest.fixture(params=["file", "s3"])
def lake(request: pytest.FixtureRequest, tmp_path: Path) -> Lake:
    if request.param == "file":
        return FileLake(tmp_path / "lake")
    result: Lake = request.getfixturevalue("s3_lake")
    return result


def test_create_is_write_once(lake: Lake) -> None:
    lake.create("bronze/x/a.gz", b"first")
    with pytest.raises(ObjectExistsError):
        lake.create("bronze/x/a.gz", b"second")
    assert lake.get("bronze/x/a.gz") == b"first"


def test_put_replaces(lake: Lake) -> None:
    lake.put("silver/t.parquet", b"v1")
    lake.put("silver/t.parquet", b"v2")
    lake.put("silver/t.parquet", b"v2")
    assert lake.get("silver/t.parquet") == b"v2"


def test_keys_lists_under_prefix_only(lake: Lake) -> None:
    for key in ("bronze/a/1", "bronze/a/2", "bronze/b/1", "silver/a/1"):
        lake.put(key, b"x")
    assert lake.keys("bronze/a/") == ["bronze/a/1", "bronze/a/2"]
    assert lake.keys("bronze/none/") == []


def test_file_lake_rejects_keys_outside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        FileLake(tmp_path / "lake").put("../outside", b"x")


def test_s3_keys_are_under_the_lake_prefix(s3_lake: S3Lake) -> None:
    s3_lake.put("silver/t.parquet", b"x")
    listed = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket="lake-test")
    assert [item["Key"] for item in listed["Contents"]] == ["lake/silver/t.parquet"]


def test_cached_lake_reads_once(s3_lake: S3Lake, tmp_path: Path) -> None:
    s3_lake.create("bronze/x/a.gz", b"raw")
    cached = CachedLake(s3_lake, tmp_path / "cache")
    assert cached.get("bronze/x/a.gz") == b"raw"
    assert (tmp_path / "cache" / "bronze/x/a.gz").read_bytes() == b"raw"


@pytest.mark.parametrize(
    "uri", [None, "", "http://x/lake", "file://host/lake", "s3:///no-bucket", "lake"]
)
def test_open_lake_rejects_bad_uris(uri: str | None) -> None:
    with pytest.raises(LakeConfigError):
        open_lake(uri)


def test_open_lake_file_uri(tmp_path: Path) -> None:
    lake = open_lake((tmp_path / "lake").as_uri())
    assert isinstance(lake, FileLake)
    assert lake.root == (tmp_path / "lake").resolve()


def test_bronze_write_layout_and_round_trip(lake: Lake) -> None:
    manifest = bronze.write(
        lake,
        source="iu_crime_log",
        body=b"<html>page</html>",
        url=URL,
        fetched_at=FETCHED,
        http_status=200,
        run_id="gha-1-1",
        ext="html",
    )
    folder = "bronze/iu_crime_log/ingest_date=2026-10-26"
    assert manifest.key == f"{folder}/20261026T204623Z_gha-1-1.html.gz"
    assert lake.keys("bronze/") == [
        f"{folder}/20261026T204623Z_gha-1-1.html.gz",
        f"{folder}/20261026T204623Z_gha-1-1.manifest.json",
    ]
    assert gzip.decompress(lake.get(manifest.key)) == b"<html>page</html>"
    assert bronze.manifests(lake, "iu_crime_log") == [manifest]
    assert bronze.read(lake, manifest) == b"<html>page</html>"
    assert bronze.latest_fetch(lake, "iu_crime_log") == FETCHED


def test_bronze_never_overwrites_a_run(lake: Lake) -> None:
    args = {"source": "s", "url": URL, "fetched_at": FETCHED, "http_status": 200, "ext": "html"}
    bronze.write(lake, body=b"one", run_id="r1", **args)  # type: ignore[arg-type]
    with pytest.raises(ObjectExistsError):
        bronze.write(lake, body=b"two", run_id="r1", **args)  # type: ignore[arg-type]
    bronze.write(lake, body=b"two", run_id="r2", **args)  # type: ignore[arg-type]
    assert len(bronze.manifests(lake, "s")) == 2


def test_bronze_read_detects_tampering(lake: Lake) -> None:
    manifest = bronze.write(
        lake,
        source="s",
        body=b"real",
        url=URL,
        fetched_at=FETCHED,
        http_status=200,
        run_id="r1",
        ext="html",
    )
    lake.put(manifest.key, gzip.compress(b"forged"))
    with pytest.raises(bronze.BronzeIntegrityError):
        bronze.read(lake, manifest)


@pytest.mark.parametrize("run_id", ["", "a/b", "a.b", "x" * 65, "has space"])
def test_run_ids_must_be_key_safe(monkeypatch: pytest.MonkeyPatch, run_id: str) -> None:
    monkeypatch.setenv("RUN_ID", run_id)
    if run_id:
        with pytest.raises(ValueError, match="run id"):
            bronze.new_run_id()
    else:
        assert bronze.new_run_id().startswith("local-")
