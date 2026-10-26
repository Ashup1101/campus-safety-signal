from pathlib import Path

import pytest
from check_commit_msg import find_violations, main, strip_git_comments


@pytest.mark.parametrize(
    "line",
    [
        "Co-Authored-By: Someone <someone@example.com>",
        "co-authored-by: someone",
        "Generated with some tool",
        "contact noreply@anthropic.com",
        "see https://claude.com/claude-code",
        "see https://claude.ai/code",
    ],
)
def test_rejects_attribution(line: str) -> None:
    assert find_violations(f"feat: add scraper\n\n{line}\n")


@pytest.mark.parametrize(
    "line",
    [
        "Co-authored-by: Ashleshupganlawar <68706281+Ashleshupganlawar@users.noreply.github.com>",
        "Co-authored-by: Ashlesh <68706281+Ashup1101@users.noreply.github.com>",
    ],
)
def test_accepts_owner_coauthor_from_squash_merge(line: str) -> None:
    assert find_violations(f"test: cover checker (#1)\n\n{line}\n") == []


@pytest.mark.parametrize(
    "line",
    [
        "Co-authored-by: Claude <209825114+claude[bot]@users.noreply.github.com>",
        "Co-authored-by: Other <12345+Ashup1101@users.noreply.github.com>",
        "Co-authored-by: X <68706281+x@users.noreply.github.com> and noreply@anthropic.com",
    ],
)
def test_rejects_coauthor_that_is_not_owner(line: str) -> None:
    assert find_violations(f"feat: add scraper\n\n{line}\n")


def test_accepts_plain_conventional_commit() -> None:
    assert find_violations("feat(ingest): add crime log scraper\n\nIdempotent upsert.\n") == []


def test_ignores_git_comments_and_verbose_diff() -> None:
    msg = (
        "fix: tighten parser\n"
        "# Generated with the git template\n"
        "# ------------------------ >8 ------------------------\n"
        "+Co-Authored-By: line inside the diff\n"
    )
    assert find_violations(strip_git_comments(msg)) == []


def test_raw_mode_checks_hash_lines(tmp_path: Path) -> None:
    pr_body = tmp_path / "pr.txt"
    pr_body.write_text("## What\n# Generated with a tool\n", encoding="utf-8")
    assert main([str(pr_body)]) == 0
    assert main(["--raw", str(pr_body)]) == 1
