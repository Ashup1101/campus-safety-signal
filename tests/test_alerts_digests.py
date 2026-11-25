"""Daily and weekly digests of lower-level reports in a watch zone. Made-up items."""

from datetime import datetime

from campus_safety.alerts import digests
from campus_safety.alerts.digests import Item
from campus_safety.alerts.rules import CLOSING

START, END = datetime(2026, 11, 23, 7, 0), datetime(2026, 11, 24, 7, 0)
ITEMS = [
    Item("theft", "E Kirkwood Ave, 400 block (Grant to Dunn)", datetime(2026, 11, 23, 22, 0)),
    Item("theft", "E Kirkwood Ave, 400 block (Grant to Dunn)", datetime(2026, 11, 24, 1, 0)),
    Item("vandalism", None, datetime(2026, 11, 23, 9, 0)),
]


def test_a_digest_counts_by_kind_and_place_at_block_level() -> None:
    draft = digests.digest("daily", "Kirkwood Avenue", START, END, ITEMS)
    assert draft is not None
    assert draft.title == "Daily digest: Kirkwood Avenue"
    assert draft.body.splitlines()[:3] == [
        "Mon Nov 23 to Tue Nov 24: 3 lower-level reports near Kirkwood Avenue.",
        "By kind: 2 thefts, 1 vandalism",
        "Where: E Kirkwood Ave, 400 block (2)",
    ]
    assert "Grant to Dunn" not in draft.body  # block level, never finer
    assert draft.body.endswith(CLOSING)


def test_an_empty_digest_is_not_sent_and_weekly_says_so() -> None:
    assert digests.digest("weekly", "Campus core", START, END, []) is None
    weekly = digests.digest("weekly", "Campus core", START, END, ITEMS[:1])
    assert weekly is not None and weekly.title == "Weekly digest: Campus core"
