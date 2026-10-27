from pathlib import Path

from launchd_job import SCRIPT, job, read_env

REPO = Path("/repo")
WORKTREE = Path("/home/u/.local/share/campus-safety-signal/ingest")


def test_job_runs_main_worktree_daily() -> None:
    plist = job(REPO, WORKTREE, "/opt/uv", {})
    assert plist["ProgramArguments"] == ["/bin/sh", "-c", SCRIPT]
    assert plist["WorkingDirectory"] == str(WORKTREE)
    assert plist["StartCalendarInterval"] == {"Hour": 11, "Minute": 17}
    assert plist["RunAtLoad"] is True
    assert plist["StandardOutPath"] == "/repo/data/logs/iu-crime-log.log"
    assert "checkout -q --detach FETCH_HEAD" in SCRIPT
    assert "iu-crime-log --data-dir" in SCRIPT


def test_job_defaults_to_the_local_file_lake() -> None:
    env = job(REPO, WORKTREE, "/opt/uv", {})["EnvironmentVariables"]
    assert env == {
        "WORKTREE": str(WORKTREE),
        "UV": "/opt/uv",
        "DATA_DIR": "/repo/data",
        "LAKE_URI": "file:///repo/data/lake",
    }


def test_job_takes_lake_and_aws_settings_from_env_file() -> None:
    settings = {"LAKE_URI": "s3://b/lake", "AWS_PROFILE": "cs", "AWS_REGION": "us-east-2"}
    env = job(REPO, WORKTREE, "/opt/uv", settings)["EnvironmentVariables"]
    assert isinstance(env, dict)
    assert {key: env[key] for key in settings} == settings


def test_read_env_keeps_only_lake_keys(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "LAKE_URI='s3://bucket/lake'\nAWS_PROFILE=\"campus\"\nSECRET_TOKEN=nope\n# comment\n"
        "AWS_REGION=us-east-2\n"
    )
    assert read_env(dotenv) == {
        "LAKE_URI": "s3://bucket/lake",
        "AWS_PROFILE": "campus",
        "AWS_REGION": "us-east-2",
    }
    assert read_env(tmp_path / "missing") == {}
