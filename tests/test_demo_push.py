"""Expo push sender with a fake HTTPS transport: no network, no Expo calls."""

import json
import logging
from typing import Any

import pytest

from demo_server.push import RECEIPTS_URL, SEND_URL, ExpoPushSender, PushMessage

TOKENS = [f"ExponentPushToken[phone{n:04d}aaaaaa]" for n in range(205)]


class Expo:
    """Answers like Expo's API: ok tickets, except tokens listed as gone."""

    def __init__(self, gone: set[str] | None = None, status: int = 200) -> None:
        self.calls: list[tuple[str, Any, dict[str, str]]] = []
        self.gone = gone or set()
        self.status = status

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        payload = json.loads(body)
        self.calls.append((url, payload, headers))
        if self.status != 200:
            return self.status, b""
        if url == SEND_URL:
            data = [
                {"status": "error", "details": {"error": "DeviceNotRegistered"}}
                if m["to"] in self.gone
                else {"status": "ok", "id": f"t-{m['to'][-12:]}"}
                for m in payload
            ]
            return 200, json.dumps({"data": data}).encode()
        found: dict[str, Any] = {i: {"status": "ok"} for i in payload["ids"]}
        found[payload["ids"][0]] = {"status": "error", "details": {"error": "MessageRateExceeded"}}
        return 200, json.dumps({"data": found}).encode()


def messages(n: int) -> list[PushMessage]:
    return [
        PushMessage(t, "Official IU alert", "Shelter in place.", {"thread_id": "x"})
        for t in TOKENS[:n]
    ]


def test_batches_of_100_with_tickets_in_order(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    expo = Expo(gone={TOKENS[3]})
    tickets = ExpoPushSender(transport=expo).send(messages(205))
    assert [len(call[1]) for call in expo.calls] == [100, 100, 5]
    assert [t.token for t in tickets] == TOKENS[:205]
    assert tickets[3].error_kind == "DeviceNotRegistered" and tickets[3].ticket_id is None
    assert tickets[0].ticket_id == f"t-{TOKENS[0][-12:]}" and tickets[0].error_kind is None
    first = expo.calls[0][1][0]
    assert first["title"] == "Official IU alert" and first["priority"] == "high"
    assert "Authorization" not in expo.calls[0][2]
    assert TOKENS[3] not in caplog.text and "Shelter" not in caplog.text


def test_the_access_token_is_sent_when_set() -> None:
    expo = Expo()
    ExpoPushSender("expo-access-for-test", transport=expo).send(messages(1))
    assert expo.calls[0][2]["Authorization"] == "Bearer expo-access-for-test"


def test_http_errors_and_network_errors_fail_the_batch_by_kind() -> None:
    assert {t.error_kind for t in ExpoPushSender(transport=Expo(status=503)).send(messages(3))} == {
        "http_503"
    }

    def down(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        raise OSError("offline")

    assert {t.error_kind for t in ExpoPushSender(transport=down).send(messages(2))} == {"OSError"}


def test_receipts_map_ids_to_ok_or_error_kind() -> None:
    expo = Expo()
    found = ExpoPushSender(transport=expo).receipts(["a", "b"])
    assert expo.calls[0][0] == RECEIPTS_URL
    assert found == {"a": "MessageRateExceeded", "b": None}


def test_categories_ride_along_for_are_you_ok() -> None:
    message = PushMessage("t", "Mom is asking: are you OK?", "Answer here.", {}, "are_you_ok")
    assert message.payload()["categoryId"] == "are_you_ok"


def _store(tmp_path: Any) -> Any:
    from datetime import UTC, datetime

    from demo_target import store_at

    from demo_server.seed import ACCOUNTS
    from demo_server.store import Store

    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    now = datetime(2026, 11, 27, tzinfo=UTC)
    store.add_device(TOKENS[0], "student_sam", "ios", now)
    store.add_device(TOKENS[1], "parent_mom", "ios", now)
    store.add_device(TOKENS[2], "parent_mom", "ios", now)
    return store


def _channel(store: Any, sender: Any) -> Any:
    from datetime import UTC, datetime

    from demo_server.push import PushChannel

    return PushChannel(store, sender, lambda: datetime(2026, 11, 27, tzinfo=UTC))


def test_one_push_per_key_and_phone_and_dead_phones_removed(tmp_path: Any) -> None:
    from demo_server.push import FakePushSender

    store = _store(tmp_path)
    fake = FakePushSender(errors={TOKENS[2]: "DeviceNotRegistered"})
    channel = _channel(store, fake)
    assert channel.deliver("alert:a1", ["student_sam", "parent_mom"], "T", "B") == 2
    assert channel.deliver("alert:a1", ["student_sam", "parent_mom"], "T", "B") == 0  # repeat key
    assert store.devices_of("parent_mom") == [TOKENS[1]]  # the dead phone is gone
    counts = store.push_counts()
    assert counts["sent"] == 2 and counts["failed"] == {"DeviceNotRegistered": 1}
    assert counts["devices"] == 2


def test_receipts_mark_delivered_or_failed_and_remove_dead_phones(tmp_path: Any) -> None:
    from demo_server.push import FakePushSender

    store = _store(tmp_path)
    fake = FakePushSender()
    channel = _channel(store, fake)
    channel.deliver("alert:a2", ["student_sam", "parent_mom"], "T", "B")
    fake.receipt_errors = {"ticket-1": "DeviceNotRegistered"}
    assert channel.check_receipts() == 3
    counts = store.push_counts()
    assert counts["delivered"] == 2 and counts["waiting_for_receipt"] == 0
    assert counts["failed"] == {"DeviceNotRegistered": 1}
    assert store.devices_of("parent_mom") == [TOKENS[2]]  # ticket-1 went to Mom's first phone
    assert channel.check_receipts() == 0


def test_the_push_log_never_holds_message_text(tmp_path: Any) -> None:
    from demo_target import columns, store_at

    _store(tmp_path)
    assert not {"title", "body", "text", "message"} & columns(store_at(tmp_path), "push_log")
