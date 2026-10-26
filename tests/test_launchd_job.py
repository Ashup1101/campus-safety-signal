from pathlib import Path

from launchd_job import job


def test_job_runs_daily_from_the_repo() -> None:
    plist = job(Path("/repo"), "/opt/uv")
    assert plist["ProgramArguments"] == ["/opt/uv", "run", "--locked", "iu-crime-log", "run"]
    assert plist["WorkingDirectory"] == "/repo"
    assert plist["StartCalendarInterval"] == {"Hour": 10, "Minute": 17}
    assert plist["RunAtLoad"] is True
    assert plist["StandardOutPath"] == "/repo/data/logs/iu-crime-log.log"
