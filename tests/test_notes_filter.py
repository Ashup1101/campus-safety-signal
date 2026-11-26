"""The community notes text filter. Every text is made up. Names come from a fake detector here;
the server uses Presidio."""

import pytest

from campus_safety.notes import config, filter

CFG = config.load()


def fake_names(text: str) -> list[str]:
    return [w for w in ("Jordan Smith",) if w in text]


def verdict(text: str) -> tuple[str, str | None]:
    found = filter.check(text, CFG, fake_names)
    return found.outcome, found.reason


@pytest.mark.parametrize(
    "text",
    ["Kirkwood closed at Dunn", "Lots of officers near the library", "Road open again at 4th"],
)
def test_plain_useful_text_passes(text: str) -> None:
    assert verdict(text) == ("ok", None)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("see https://example.test/x", "link"),
        ("go to example dot com now", "link"),
        ("details at bit[.]ly/abc", "link"),
        ("email me at kim@example.test", "email"),
        ("call 812-555-0100", "phone number"),
        ("text 8125550100", "phone number"),
        ("venmo me for gas", "money"),
        ("send $20 please", "money"),
        ("white male wearing a red hoodie", "description of a person"),
        ("Jordan Smith was there", "name"),
        ("x" * 141, "too long"),
        ("Kirkwood​ closed", "hidden characters"),
    ],
)
def test_blocked_with_a_plain_reason(text: str, reason: str) -> None:
    assert verdict(text) == ("blocked", reason)


@pytest.mark.parametrize("text", ["heard a SHOOTER?", "possible bomb threat", "guy with a gun"])
def test_alarming_words_wait_for_review(text: str) -> None:
    assert verdict(text) == ("held", "needs review")
