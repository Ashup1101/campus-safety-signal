"""The web and iPhone apps share one contract and one set of design tokens: identical copies."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ["api.ts", "tokens.json"]


@pytest.mark.parametrize("name", SHARED)
def test_web_and_mobile_copies_are_identical(name: str) -> None:
    web = (ROOT / "apps" / "web" / "src" / "shared" / name).read_text()
    mobile = (ROOT / "apps" / "mobile" / "src" / "shared" / name).read_text()
    assert web == mobile, f"edit apps/web/src/shared/{name}, then copy it to apps/mobile"


def test_red_is_reserved_for_live_official_alerts() -> None:
    tokens = json.loads((ROOT / "apps" / "web" / "src" / "shared" / "tokens.json").read_text())
    official = tokens["alert"]["official"]
    red = {official["light"].lower(), official["dark"].lower()}
    others = [
        value.lower()
        for group, entries in tokens.items()
        if isinstance(entries, dict)
        for key, entry in entries.items()
        if (group, key) != ("alert", "official") and isinstance(entry, dict)
        for value in entry.values()
        if isinstance(value, str) and value.startswith("#")
    ]
    assert red.isdisjoint(others)


def test_server_and_apps_share_the_check_in_lists() -> None:
    import re

    from demo_server.hub import CHECK_IN_STATES, SHELTER_PLACES

    api = (ROOT / "apps" / "web" / "src" / "shared" / "api.ts").read_text()
    places = re.search(r"SHELTER_PLACES = \[(.*?)\] as const", api, re.DOTALL)
    states = re.search(r"export type CheckInState = (.*?);", api)
    assert places and states
    assert tuple(re.findall(r'"([^"]+)"', places.group(1))) == SHELTER_PLACES
    assert tuple(re.findall(r'"([^"]+)"', states.group(1))) == CHECK_IN_STATES


def test_apps_and_server_agree_on_when_a_thread_stops_being_live() -> None:
    import re

    from demo_server.threads import THREAD_GAP

    api = (ROOT / "apps" / "web" / "src" / "shared" / "api.ts").read_text()
    found = re.search(r"THREAD_GAP_MS = (\d+) \* (\d+) \* (\d+) \* (\d+);", api)
    assert found
    hours, minutes, seconds, ms = (int(g) for g in found.groups())
    assert hours * minutes * seconds * ms == THREAD_GAP.total_seconds() * 1000
