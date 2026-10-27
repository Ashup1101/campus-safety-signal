from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from campus_safety.lake.cli import main


def test_backup_notes_copies_claude_md_and_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("LAKE_URI", "s3://lake-test/lake")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("rules")
    (tmp_path / ".notes" / "interview").mkdir(parents=True)
    (tmp_path / ".notes" / "STATE.md").write_text("state")
    (tmp_path / ".notes" / "interview" / "phase-01.md").write_text("notes")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="lake-test")
        assert main(["backup-notes"]) == 0
        keys = [item["Key"] for item in s3.list_objects_v2(Bucket="lake-test")["Contents"]]
    assert keys == [
        "_private/notes/.notes/STATE.md",
        "_private/notes/.notes/interview/phase-01.md",
        "_private/notes/CLAUDE.md",
    ]


def test_backup_notes_needs_an_s3_lake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LAKE_URI", (tmp_path / "lake").as_uri())
    assert main(["backup-notes"]) == 1
