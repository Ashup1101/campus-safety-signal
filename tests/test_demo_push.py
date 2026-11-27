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
