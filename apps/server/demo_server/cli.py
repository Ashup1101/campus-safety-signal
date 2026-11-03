"""python -m demo_server serve | seed | drill | all-clear | replay <id>

drill, all-clear and replay talk to the running local server as the demo console account.
"""

import argparse
import json
import logging
import sys
import urllib.request
from typing import Any

from demo_server.seed import Settings, seed
from demo_server.store import Store

# 8100 / 3100: ports 8000 and 3000 are often taken by other local projects.
PORT = 8100
SERVER = f"http://127.0.0.1:{PORT}"


def _post(path: str, body: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 (fixed loopback URL)
        SERVER + path, json.dumps(body).encode(), headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        data: dict[str, Any] = json.loads(response.read())
        return data


def _as_console(path: str, body: dict[str, Any] | None = None) -> None:
    token = _post("/api/login", {"account_id": "console"})["token"]
    print(_post(path, body or {}, token)["status"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo_server")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the local demo server on 127.0.0.1:8100")
    serve.add_argument("--no-live-feed", action="store_true", help="do not poll IU's alert feed")
    commands.add_parser("seed", help="(re)build demo accounts and activity levels")
    commands.add_parser("drill", help='send "DRILL: Shelter in place, avoid Kirkwood Avenue."')
    commands.add_parser("all-clear", help="send the drill all-clear")
    replay = commands.add_parser("replay", help="replay a past night (test accounts only)")
    replay.add_argument("replay_id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "serve":
        import uvicorn

        from demo_server.app import create_app

        app = create_app(Settings(live_feed=not args.no_live_feed))
        uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False, ws_max_size=65536)
    elif args.command == "seed":
        settings = Settings()
        store = Store(settings.db)
        seed(store, settings)
        store.close()
    elif args.command == "drill":
        _as_console("/api/drill", {"action": "drill"})
    elif args.command == "all-clear":
        _as_console("/api/drill", {"action": "all_clear"})
    else:
        _as_console(f"/api/replays/{args.replay_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
