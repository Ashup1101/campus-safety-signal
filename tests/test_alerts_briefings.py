"""Pre-event briefings: templated notes before an event night. Made-up street levels."""

from datetime import date

from campus_safety.alerts import briefings
from campus_safety.alerts.briefings import Busy
from campus_safety.alerts.rules import CLOSING
from campus_safety.events import Event

HALLOWEEN = Event(
    "halloween_2026", "Halloween weekend", (date(2026, 10, 30), date(2026, 10, 31)), "x"
)
STREETS = [
    Busy(
        "E Kirkwood Ave, 400 block (Grant to Dunn)",
        "high",
        "2 shootings on event nights in 2026",
        2,
    ),
    Busy("N Dunn St, 500 block (9th to 10th)", "elevated", "3 thefts on event nights 2024-2026", 3),
    Busy(
        "E 3rd St, 1300 block (Highland to Eagleson)",
        "elevated",
        "2 thefts on event nights in 2025",
        2,
    ),
    Busy(
        "E 10th St, 600 block (Indiana to Fess)", "elevated", "1 theft on event nights in 2026", 1
    ),
    Busy("N Fess Ave, 300 block (7th to 8th)", "quiet", "Nothing recorded on event nights", 0),
]


def test_a_briefing_names_the_event_the_busiest_streets_and_the_links() -> None:
    draft = briefings.briefing(HALLOWEEN, STREETS, "busier than usual (simple rule)")
    assert draft.title == "Before Halloween weekend (Fri Oct 30 and Sat Oct 31)"
    lines = draft.body.splitlines()
    assert lines[2:5] == [
        "- E Kirkwood Ave, 400 block (Grant to Dunn): High. 2 shootings on event nights in 2026",
        "- N Dunn St, 500 block (9th to 10th): Elevated. 3 thefts on event nights 2024-2026",
        "- E 3rd St, 1300 block (Highland to Eagleson): Elevated. 2 thefts on event nights in 2025",
    ]
    assert "Tonight near campus: busier than usual (simple rule)." in draft.body
    assert all(url in draft.body for _, url in briefings.LINKS)
    assert draft.body.endswith(CLOSING)


def test_without_busy_streets_or_a_forecast_it_says_so_plainly() -> None:
    draft = briefings.briefing(HALLOWEEN, STREETS[-1:], None)
    assert "No street stood out on past event nights in the data we hold." in draft.body
    assert "Tonight near campus" not in draft.body
    streets = draft.body.split("Links:")[0].lower()
    assert "safe" not in streets and "risk" not in streets
