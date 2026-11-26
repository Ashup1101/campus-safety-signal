"""Corroboration and live-alert rules for community notes. Made-up notes."""

from campus_safety.notes import config, rules

CFG = config.load()


def note(
    account: str, tag: str, text: str | None = None, state: str = "pending"
) -> dict[str, object]:
    return {"account_id": account, "tag": tag, "text": text, "state": state}


def test_a_tag_shows_once_two_people_agree() -> None:
    one = [note("a", "Road closed", "Dunn closed")]
    assert rules.corroborated(one, event_night=False, cfg=CFG) == []
    two = [*one, note("b", "Road closed"), note("c", "Crowd gathering", "big crowd")]
    assert rules.corroborated(two, event_night=False, cfg=CFG) == [
        {"tag": "Road closed", "people": 2, "texts": ["Dunn closed"]}
    ]


def test_event_nights_need_three_and_held_or_hidden_notes_never_count() -> None:
    notes = [note("a", "Road closed"), note("b", "Road closed")]
    assert rules.corroborated(notes, event_night=True, cfg=CFG) == []
    notes += [note("c", "Road closed", state="held"), note("d", "Road closed", state="hidden")]
    assert rules.corroborated(notes, event_night=True, cfg=CFG) == []
    notes.append(note("e", "Road closed", "closed at 4th"))
    assert rules.corroborated(notes, event_night=True, cfg=CFG)[0]["people"] == 3


def test_text_only_from_people_whose_tag_is_corroborated() -> None:
    notes = [note("a", "Road closed"), note("b", "Road closed"), note("c", "Quiet now", "all calm")]
    found = rules.corroborated(notes, event_night=False, cfg=CFG)
    assert [f["tag"] for f in found] == ["Road closed"] and found[0]["texts"] == []
