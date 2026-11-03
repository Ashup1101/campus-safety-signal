"""Download the demo's offline map into data/demo/tiles/ (served by the demo server at /tiles):
a small Bloomington extract of the Protomaps daily basemap, plus the fonts and sprites its style
needs. Run via `make demo-assets`, which passes a pinned, checksum-verified pmtiles CLI.

Robots.txt is checked for every host first; files already present are kept.
"""

import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from campus_safety import fetch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo" / "tiles"
BUILDS = "https://build-metadata.protomaps.dev/builds.json"
BUILD = "https://build.protomaps.com/{key}"
BBOX = "-86.548,39.150,-86.495,39.188"  # downtown + campus
MAXZOOM = 15
ASSETS = "https://protomaps.github.io/basemaps-assets"
FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"]
GLYPH_RANGES = ["0-255", "8192-8447"]
SPRITES = [
    f"{flavor}{scale}.{ext}"
    for flavor in ("light", "dark")
    for scale in ("", "@2x")
    for ext in ("json", "png")
]


def extract(pmtiles: str) -> None:
    target = OUT / "bloomington.pmtiles"
    if target.exists():
        return
    builds = json.loads(fetch.polite_get(BUILDS).body)
    key = max(b["key"] for b in builds if str(b["key"]).endswith(".pmtiles"))
    url = BUILD.format(key=key)
    fetch.check_robots(url)
    partial = target.with_suffix(".partial")
    subprocess.run(  # noqa: S603 (pinned binary from the Makefile, fixed arguments)
        [pmtiles, "extract", url, str(partial), f"--bbox={BBOX}", f"--maxzoom={MAXZOOM}"],
        check=True,
    )
    partial.rename(target)
    print(f"map extract from {key}: {target.stat().st_size // 1024} KiB")


def download(url: str, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fetch.polite_get(url).body)
    time.sleep(0.5)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: fetch_demo_assets.py <pmtiles binary>", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    extract(argv[1])
    for font in FONTS:
        for glyphs in GLYPH_RANGES:
            url = f"{ASSETS}/fonts/{urllib.parse.quote(font)}/{glyphs}.pbf"
            download(url, OUT / "fonts" / font / f"{glyphs}.pbf")
    for name in SPRITES:
        download(f"{ASSETS}/sprites/v4/{name}", OUT / "sprites" / "v4" / name)
    print(f"offline map assets ready in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
