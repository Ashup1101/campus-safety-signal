"""Start and stop every local demo process: server, web app, iPhone app in one Simulator.

Each process runs under `nice` in its own process group; the group ids go to data/demo/run/, and
`stop` ends exactly those groups (never anything matched by name), then shuts the Simulator down.
`walk` and `walk-home` move the Simulator's location along Kirkwood with `xcrun simctl location`.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "demo" / "run"
WEB, MOBILE = ROOT / "apps" / "web", ROOT / "apps" / "mobile"

PROCESSES: dict[str, tuple[list[str], Path, dict[str, str]]] = {
    "server": (
        ["uv", "run", "python", "-m", "demo_server", "serve"],
        ROOT,
        {"PYTHONPATH": "apps/server"},
    ),
    "web": (["npm", "run", "dev"], WEB, {"NEXT_TELEMETRY_DISABLED": "1"}),
    "mobile": (["npx", "expo", "start", "--ios"], MOBILE, {"EXPO_NO_TELEMETRY": "1"}),
}

# (lat, lon) waypoints. Downtown east along Kirkwood into the 400 block (Grant to Dunn).
WALK = [
    (39.166591, -86.533613),
    (39.166565, -86.531083),
    (39.166553, -86.529811),
    (39.16655, -86.5290),
]
# From the 400 block home (the home point in apps/mobile/src/geo.ts) via Indiana Ave and 7th St.
WALK_HOME = [
    (39.16655, -86.5290),
    (39.16655, -86.52693),
    (39.16851, -86.52696),
    (39.16862, -86.51745),
]
SPEED_M_PER_S = 6


def simulator() -> bool:
    if shutil.which("xcrun") is None:
        return False
    return subprocess.run(["xcrun", "simctl", "help"], capture_output=True).returncode == 0  # noqa: S607


def start() -> int:
    stop(quiet=True)
    RUN.mkdir(parents=True, exist_ok=True)
    for name, (command, cwd, env) in PROCESSES.items():
        if name == "mobile" and not simulator():
            print("mobile: skipped (no iPhone Simulator; install Xcode from the App Store)")
            continue
        if name != "server" and not (cwd / "node_modules").exists():
            subprocess.run(["npm", "ci", "--no-fund", "--no-audit"], cwd=cwd, check=True)  # noqa: S607
        with (RUN / f"{name}.log").open("w") as log:
            process = subprocess.Popen(  # noqa: S603 (fixed commands above)
                ["nice", "-n", "10", *command],  # noqa: S607
                cwd=cwd,
                env={**os.environ, **env},
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (RUN / f"{name}.pid").write_text(str(process.pid))
        print(f"{name}: started (log: data/demo/run/{name}.log)")
    print("Parent view: http://localhost:3100/parent   Console: http://localhost:3100/console")
    return 0


def stop(quiet: bool = False) -> int:
    groups = []
    for pid_file in RUN.glob("*.pid") if RUN.exists() else []:
        groups.append(int(pid_file.read_text()))
        pid_file.unlink()
    for signal_ in (signal.SIGTERM, signal.SIGKILL):
        for group in groups:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(group, signal_)
        if signal_ == signal.SIGTERM and groups:
            time.sleep(2)
    has_simulator = simulator()
    if has_simulator:
        subprocess.run(["xcrun", "simctl", "shutdown", "all"], capture_output=True)  # noqa: S607
        subprocess.run(["osascript", "-e", 'quit app "Simulator"'], capture_output=True)  # noqa: S607
    if not quiet:
        closed = ", Simulator shut down" if has_simulator else ""
        print(f"demo stopped ({len(groups)} process groups{closed})")
    return 0


def walk(points: list[tuple[float, float]]) -> int:
    if not simulator():
        print("no iPhone Simulator (install Xcode)", file=sys.stderr)
        return 1
    waypoints = [f"{lat},{lon}" for lat, lon in points]
    subprocess.run(  # noqa: S603
        ["xcrun", "simctl", "location", "booted", "start", f"--speed={SPEED_M_PER_S}", *waypoints],  # noqa: S607
        check=True,
    )
    print(f"walking {len(points)} waypoints at {SPEED_M_PER_S} m/s")
    return 0


def main(argv: list[str]) -> int:
    commands: dict[str, Callable[[], int]] = {
        "start": start,
        "stop": stop,
        "walk": lambda: walk(WALK),
        "walk-home": lambda: walk(WALK_HOME),
    }
    if len(argv) != 2 or argv[1] not in commands:
        print(f"usage: demo.py {'|'.join(commands)}", file=sys.stderr)
        return 2
    return commands[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
