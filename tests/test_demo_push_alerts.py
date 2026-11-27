"""Official alerts and follow-ups by push (fake sender): same words, after the socket relay."""

import asyncio
import time
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


@pytest.mark.parametrize(("mode", "pushed"), [("off", 0), ("expo", 4)])
def test_push_mode_decides_whether_a_drill_is_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, pushed: int
) -> None:
    from fastapi.testclient import TestClient

    from demo_server import push
    from demo_server.app import create_app
    from demo_server.seed import Settings

    fake = FakePushSender()
    monkeypatch.setattr(push, "ExpoPushSender", lambda token=None: fake)
    settings = Settings(
        data_dir=tmp_path / "d",
        warehouse=tmp_path / "n.duckdb",
        tiles=tmp_path / "t",
        push_mode=mode,
    )
    app = create_app(settings)
    store = app.state.store
    for account in ACCOUNTS:
        if account.role != "console":
            store.add_device(phone(account.id.replace("_", "")), account.id, "ios", NOW)
    with TestClient(app) as client:
        token = client.post("/api/login", json={"account_id": "console"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            client.post("/api/drill", headers=headers, json={"action": "drill"}).status_code == 200
        )
        for _ in range(50):  # the drill source relays in the background
            if len(fake.sent) >= pushed:
                break
            time.sleep(0.05)
    assert len(fake.sent) == pushed


def test_are_you_ok_by_push_answered_with_its_token_once(store: Store) -> None:
    async def run() -> tuple[list[dict[str, object]], bool, bool, bool]:
        hub, fake = hub_with_push(store)
        mom = next(a for a in ACCOUNTS if a.id == "parent_mom")
        heard: list[dict[str, object]] = []

        class Peer:
            async def send_json(self, data: dict[str, object]) -> None:
                heard.append(data)

        await hub.join(mom, Peer())  # type: ignore[arg-type]
        request_id = await hub.ask_ok(mom, "student_sam")
        assert request_id is not None
        push = fake.sent[-1]
        assert push.to == phone("studentsam") and push.category == "are_you_ok"
        assert push.title == "Mom is asking: are you OK?"
        token = str(push.data["answer_token"])
        wrong = await hub.answer_ok_by_token(request_id, "not-the-token-at-all", "ok")
        right = await hub.answer_ok_by_token(request_id, token, "ok")
        again = await hub.answer_ok_by_token(request_id, token, "ok")
        return heard, wrong, right, again

    heard, wrong, right, again = asyncio.run(run())
    assert (wrong, right, again) == (False, True, False)
    assert {"type": "ok_result", "state": "ok"}.items() <= heard[-1].items()


def test_an_expired_answer_token_is_refused(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from demo_server import hub as hub_module  # its monotonic clock is replaced below

    async def run() -> bool:
        hub, fake = hub_with_push(store)
        mom = next(a for a in ACCOUNTS if a.id == "parent_mom")
        request_id = await hub.ask_ok(mom, "student_sam")
        assert request_id is not None
        token = str(fake.sent[-1].data["answer_token"])
        later = time.monotonic() + hub.ok_timeout + 1
        monkeypatch.setattr(hub_module, "monotonic", lambda: later)
        return await hub.answer_ok_by_token(request_id, token, "ok")

    assert asyncio.run(run()) is False


def test_the_answer_endpoint_refuses_unknown_requests(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from demo_server.app import create_app
    from demo_server.seed import Settings

    app = create_app(
        Settings(data_dir=tmp_path / "d", warehouse=tmp_path / "n.duckdb", tiles=tmp_path / "t")
    )
    client = TestClient(app)
    body = {"token": "x" * 20, "answer": "ok"}
    assert client.post("/api/ok/nope", json=body).status_code == 404
    assert (
        client.post("/api/ok/nope", json={"token": "x" * 20, "answer": "maybe"}).status_code == 422
    )
