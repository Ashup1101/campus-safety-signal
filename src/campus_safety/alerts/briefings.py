"""Pre-event briefings: a short templated note sent the afternoon before an event night (events
in configs/events.yaml). It names the streets that were busiest on past event nights (activity
levels, which never include sensitive offenses), tonight's expected level when a forecast covers
it, and official IU links. Templates only: no LLM writes it, no names, no business names, never
the words safe or risk."""

from collections.abc import Sequence
from dataclasses import dataclass

from campus_safety.alerts.rules import CLOSING, Draft
from campus_safety.events import Event

TOP = 3
LINKS = (
    (
        "IU Notify alerts and the Guardian app",
        "https://protect.iu.edu/emergency-continuity/emergency-alerts/guardian-app.html",
    ),
    (
        "IU Bloomington emergency contacts and night escort",
        "https://protect.iu.edu/emergency-continuity/emergency-contacts/iub.html",
    ),
    ("IU's live alert page", "https://emergency.iu.edu/rave/index.html"),
)
RANK = {"high": 2, "elevated": 1}


@dataclass(frozen=True)
class Busy:
    name: str  # segment name, e.g. "E Kirkwood Ave, 400 block (Grant to Dunn)"
    level: str  # quiet | elevated | high (event-night window)
    reason: str
    incidents: int


def _dates(event: Event) -> str:
    days = [n.strftime("%a %b %-d") for n in sorted(event.nights)]
    return days[0] if len(days) == 1 else ", ".join(days[:-1]) + " and " + days[-1]


def busiest(streets: Sequence[Busy], top: int = TOP) -> list[Busy]:
    ranked = [s for s in streets if s.level in RANK]
    return sorted(ranked, key=lambda s: (-RANK[s.level], -s.incidents, s.name))[:top]


def briefing(event: Event, streets: Sequence[Busy], tonight: str | None) -> Draft:
    top = busiest(streets)
    lines = [f"{event.name} is coming up.", "Streets that were busiest on past event nights:"]
    lines += [f"- {s.name}: {s.level.capitalize()}. {s.reason}" for s in top] or [
        "No street stood out on past event nights in the data we hold."
    ]
    if tonight:
        lines.append(f"Tonight near campus: {tonight}.")
    lines.append("Agree on a check-in time and a way home before the night starts.")
    lines.append("Links: " + "; ".join(f"{label}: {url}" for label, url in LINKS))
    lines.append(CLOSING)
    return Draft(f"Before {event.name} ({_dates(event)})", "\n".join(lines))
