"""Reject commit messages and PR text that carry AI attribution."""

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = re.compile(
    r"co-authored-by:|generated with|noreply@anthropic\.com"
    r"|claude\.com/claude-code|claude\.ai/code",
    re.IGNORECASE,
)
SCISSORS = "# ------------------------ >8 ------------------------"


def strip_git_comments(text: str) -> str:
    # The commit-msg hook sees git's template comments and, with -v, a diff below the
    # scissors line. Neither ends up in the commit, so neither should trip the check.
    body = text.split(SCISSORS, 1)[0]
    return "\n".join(line for line in body.splitlines() if not line.startswith("#"))


def find_violations(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--raw", action="store_true", help="check every line; for stored commits and PR text"
    )
    args = parser.parse_args(argv)

    status = 0
    for path in args.paths:
        text = path.read_text(encoding="utf-8")
        hits = find_violations(text if args.raw else strip_git_comments(text))
        if hits:
            print(f"{path}: forbidden attribution: {', '.join(hits)}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
