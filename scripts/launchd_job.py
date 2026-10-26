"""Install or remove the macOS LaunchAgent that runs `iu-crime-log run` daily.

launchd runs a missed calendar job when the Mac wakes, and RunAtLoad covers login after a
shutdown; the command's own 12-hour guard keeps those extra starts from fetching twice.
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
REPO = Path(__file__).resolve().parent.parent


def job(repo: Path, uv: str) -> dict[str, object]:
    log_file = str(repo / "data" / "logs" / "iu-crime-log.log")
    return {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "--locked", "iu-crime-log", "run"],
        "WorkingDirectory": str(repo),
        "StartCalendarInterval": {"Hour": 10, "Minute": 17},
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": log_file,
        "StandardErrorPath": log_file,
    }


def install() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv not found on PATH")
    (REPO / "data" / "logs").mkdir(parents=True, exist_ok=True)
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(plistlib.dumps(job(REPO, uv)))
    domain = f"gui/{os.getuid()}"
    # Fixed argv, no shell. bootout first so reinstalling picks up a changed plist.
    subprocess.run([LAUNCHCTL, "bootout", f"{domain}/{LABEL}"], check=False, capture_output=True)  # noqa: S603
    subprocess.run([LAUNCHCTL, "bootstrap", domain, str(AGENT)], check=True)  # noqa: S603
    print(f"installed {AGENT}; log: {job(REPO, uv)['StandardOutPath']}")


def uninstall() -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run([LAUNCHCTL, "bootout", f"{domain}/{LABEL}"], check=False, capture_output=True)  # noqa: S603
    AGENT.unlink(missing_ok=True)
    print(f"removed {AGENT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall"])
    if parser.parse_args().action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
