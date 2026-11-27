"""Official alerts and follow-ups by push (fake sender): same words, after the socket relay."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from demo_target import store_at

from campus_safety.alerts.rules import Draft
from campus_safety.official.alerts import OfficialAlert
from demo_server.hub import Clock, Hub
from demo_server.push import FakePushSender, PushChannel
from demo_server.seed import ACCOUNTS, LINKS
from demo_server.store import Account, Store

NOW = datetime(2026, 11, 27, tzinfo=UTC)
REAL = Account("real_parent", "parent", "Real parent", False)
TEXT = "DRILL: Shelter in place, avoid Kirkwood Avenue."


def phone(name: str) -> str:
    return f"ExponentPushToken[{name}aaaaaaaaaaaa]"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(store_at(tmp_path))
    for account in [*ACCOUNTS, REAL]:
        store.add_account(account)
        store.add_device(phone(account.id.replace("_", "")), account.id, "ios", NOW)
    for parent, student, label in LINKS:
        store.link(parent, student, label)
    return store


def hub_with_push(store: Store) -> tuple[Hub, FakePushSender]:
    hub, fake = Hub(store, Clock(), {}), FakePushSender()
    hub.push = PushChannel(store, fake, lambda: NOW)
    return hub, fake


def alert(test_only: bool, text: str = TEXT, status: str = "Severe") -> OfficialAlert:
    return OfficialAlert(
        source="drill" if test_only else "iu_rave_feed",
        kind="web_page",
        text=text,
        verification="drill" if test_only else "official",  # drills reach test accounts only
        status=status,
        official_at=NOW,
    )


def test_an_official_alert_goes_verbatim_to_every_family_phone_once(store: Store) -> None:
    hub, fake = hub_with_push(store)
    body = asyncio.run(hub.publish(alert(test_only=False)))
    phones = sorted(m.to for m in fake.sent)
    assert phones == sorted(
        phone(a) for a in ("studentsam", "studentalex", "parentmom", "parentdad", "realparent")
    )
    assert {m.title for m in fake.sent} == {"Official IU alert"}
    assert {m.body for m in fake.sent} == {TEXT}  # verbatim, DRILL kept
    assert all(m.data == {"thread_id": body["thread_id"]} for m in fake.sent)
    assert phone("console") not in phones


def test_test_only_alerts_reach_test_accounts_only(store: Store) -> None:
    hub, fake = hub_with_push(store)
    asyncio.run(hub.publish(alert(test_only=True)))
    assert phone("realparent") not in {m.to for m in fake.sent} and len(fake.sent) == 4


def test_the_all_clear_is_its_own_push(store: Store) -> None:
    hub, fake = hub_with_push(store)
    asyncio.run(hub.publish(alert(test_only=True)))
    asyncio.run(hub.publish(alert(test_only=True, text="DRILL: All clear.", status="Normal")))
    assert [m.title for m in fake.sent].count("IU all-clear") == 4


def test_followups_push_to_their_recipients_once(store: Store) -> None:
    hub, fake = hub_with_push(store)
    draft = Draft("Update near Kirkwood", "Police report the area is clear.")
    asyncio.run(hub.publish_followup("i1", "alert", draft, ["parent_mom"]))
    asyncio.run(hub.publish_followup("i1", "alert", draft, ["parent_mom"]))  # refused repeat
    assert [m.to for m in fake.sent] == [phone("parentmom")]
    assert fake.sent[0].title == "Update near Kirkwood" and fake.sent[0].data == {
        "thread_id": "incident-i1"
    }


def test_without_a_push_channel_nothing_is_pushed(store: Store) -> None:
    hub = Hub(store, Clock(), {})
    asyncio.run(hub.publish(alert(test_only=True)))
    assert store.push_counts()["sent"] == 0
