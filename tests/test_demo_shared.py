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


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_cream_and_crimson_text_meets_aa_contrast(theme: str) -> None:
    tokens = json.loads((ROOT / "apps" / "web" / "src" / "shared" / "tokens.json").read_text())
    brand = {k: v[theme] for k, v in tokens["brand"].items()}
    assert _contrast(brand["ink"], brand["surface"]) >= 4.5
    assert _contrast(brand["muted"], brand["surface"]) >= 4.5
    assert _contrast(brand["crimson"], brand["surface"]) >= 4.5  # crimson buttons and links
    assert brand["crimson"].lower() not in {
        tokens["alert"]["official"]["light"].lower(),
        tokens["alert"]["official"]["dark"].lower(),
    }


def test_the_iphone_app_reaches_the_demo_server_on_ipv4() -> None:
    """The server binds 127.0.0.1; "localhost" can resolve to ::1 in the Simulator and hang."""
    client = (ROOT / "apps" / "mobile" / "src" / "client.ts").read_text()
    assert '"http://127.0.0.1:8100"' in client
    assert "localhost:8100" not in client
