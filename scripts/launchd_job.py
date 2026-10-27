"""Install or remove the macOS LaunchAgent that backs up the daily GitHub Actions ingest.

The job runs from a git worktree that follows origin/main (fetched before each run), never from
the working tree, so a half-finished branch can't break capture. LAKE_URI, AWS_PROFILE, and
AWS_REGION are read from .env at install time and written into the agent explicitly; reinstall
after changing them. It starts at 11:17 and at login, and `run`'s 12-hour bronze guard skips it
when the Actions job already captured.
"""

import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

LABEL = "io.github.ashup1101.campus-safety-signal.iu-crime-log"
AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LAUNCHCTL = "/bin/launchctl"
GIT = "/usr/bin/git"
REPO = Path(__file__).resolve().parent.parent
WORKTREE = Path.home() / ".local" / "share" / "campus-safety-signal" / "ingest"
ENV_KEYS = ("LAKE_URI", "AWS_PROFILE", "AWS_REGION")

# Paths arrive as environment variables, so nothing here is interpolated into the shell text.
# If the fetch fails (offline), the job runs the main it already has.
SCRIPT = (
    'git -C "$WORKTREE" fetch -q origin main'
    ' && git -C "$WORKTREE" checkout -q --detach FETCH_HEAD; '
    'exec "$UV" run --locked --no-dev iu-crime-log --data-dir "$DATA_DIR" run'
)


def read_env(path: Path) -> dict[str, str]:
    """The lake keys from .env, read as KEY=value lines; the file is never sourced."""
    found: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in ENV_KEYS:
                found[key.strip()] = value.strip().strip("'\"")
    return found


def job(repo: Path, worktree: Path, uv: str, env: dict[str, str]) -> dict[str, object]:
    data_dir = repo / "data"
    log_file = str(data_dir / "logs" / "iu-crime-log.log")
    return {
        "Label": LABEL,
        "ProgramArguments": ["/bin/sh", "-c", SCRIPT],
        "WorkingDirectory": str(worktree),
        "EnvironmentVariables": {
            "WORKTREE": str(worktree),
            "UV": uv,
            "DATA_DIR": str(data_dir),
            "LAKE_URI": (data_dir / "lake").as_uri(),
            **env,
        },
        "StartCalendarInterval": {"Hour": 11, "Minute": 17},
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": log_file,
        "StandardErrorPath": log_file,
    }


def _git(*args: str) -> None:
    subprocess.run([GIT, "-C", str(REPO), *args], check=True)  # noqa: S603


def install() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv not found on PATH")
    if not WORKTREE.exists():
        _git("fetch", "-q", "origin", "main")
        _git("worktree", "add", "--detach", str(WORKTREE), "FETCH_HEAD")
    if (WORKTREE / "data").is_symlink():  # left by the pre-lake setup
        (WORKTREE / "data").unlink()
    (REPO / "data" / "logs").mkdir(parents=True, exist_ok=True)
    plist = job(REPO, WORKTREE, uv, read_env(REPO / ".env"))
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(plistlib.dumps(plist))
    domain = f"gui/{os.getuid()}"
    # Fixed argv, no shell. bootout first so reinstalling picks up a changed plist.
    subprocess.run([LAUNCHCTL, "bootout", f"{domain}/{LABEL}"], check=False, capture_output=True)  # noqa: S603
    subprocess.run([LAUNCHCTL, "bootstrap", domain, str(AGENT)], check=True)  # noqa: S603
    lake = plist["EnvironmentVariables"]["LAKE_URI"]  # type: ignore[index]
    print(
        f"installed {AGENT}\n  worktree {WORKTREE}\n  lake {lake}\n  log {plist['StandardOutPath']}"
    )


def uninstall() -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run([LAUNCHCTL, "bootout", f"{domain}/{LABEL}"], check=False, capture_output=True)  # noqa: S603
    AGENT.unlink(missing_ok=True)
    print(f"removed {AGENT}; the worktree stays: git worktree remove {WORKTREE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall"])
    if parser.parse_args().action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
