"""Push notifications through Expo's push service (v14). The sender is behind a small protocol so
tests use a fake; no test or CI run ever calls Expo. Tokens and message text are never logged."""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)
SEND_URL = "https://exp.host/--/api/v2/push/send"
RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
BATCH = 100  # Expo accepts up to 100 messages per request
RECEIPT_BATCH = 1000
GONE = "DeviceNotRegistered"  # the token is dead: remove it


@dataclass(frozen=True)
class PushMessage:
    to: str
    title: str
    body: str
    data: dict[str, Any] = field(default_factory=dict)
    category: str | None = None

    def payload(self) -> dict[str, Any]:
        found: dict[str, Any] = {
            "to": self.to,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "sound": "default",
            "priority": "high",
        }
        if self.category:
            found["categoryId"] = self.category
        return found


@dataclass(frozen=True)
class Ticket:
    token: str
    ticket_id: str | None
    error_kind: str | None = None


class PushSender(Protocol):
    def send(self, messages: Sequence[PushMessage]) -> list[Ticket]: ...

    def receipts(self, ticket_ids: Sequence[str]) -> dict[str, str | None]:
        """ticket id -> None (delivered to Apple) or the error kind; missing ids are not ready."""
        ...


Transport = Callable[[str, bytes, dict[str, str]], tuple[int, bytes]]


def https_transport(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 (fixed https URLs)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""


class ExpoPushSender:
    def __init__(
        self, access_token: str | None = None, transport: Transport = https_transport
    ) -> None:
        self._token = access_token or None
        self._transport = transport

    def _post(self, url: str, payload: Any) -> tuple[int, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "campus-safety-signal-server",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        status, raw = self._transport(url, json.dumps(payload).encode(), headers)
        return status, (json.loads(raw) if raw else {})

    def send(self, messages: Sequence[PushMessage]) -> list[Ticket]:
        tickets: list[Ticket] = []
        for start in range(0, len(messages), BATCH):
            batch = messages[start : start + BATCH]
            try:
                status, body = self._post(SEND_URL, [m.payload() for m in batch])
            except Exception as exc:  # network trouble: every message in the batch failed
                tickets += [Ticket(m.to, None, type(exc).__name__) for m in batch]
                continue
            data = body.get("data") if status == 200 else None
            if not isinstance(data, list) or len(data) != len(batch):
                tickets += [Ticket(m.to, None, f"http_{status}") for m in batch]
                continue
            for message, item in zip(batch, data, strict=True):
                if item.get("status") == "ok":
                    tickets.append(Ticket(message.to, str(item.get("id"))))
                else:
                    kind = (item.get("details") or {}).get("error") or "error"
                    tickets.append(Ticket(message.to, None, str(kind)))
        failed = sum(1 for t in tickets if t.error_kind)
        if failed:
            log.warning("push: %d of %d not accepted", failed, len(tickets))
        return tickets

    def receipts(self, ticket_ids: Sequence[str]) -> dict[str, str | None]:
        found: dict[str, str | None] = {}
        for start in range(0, len(ticket_ids), RECEIPT_BATCH):
            ids = list(ticket_ids[start : start + RECEIPT_BATCH])
            try:
                status, body = self._post(RECEIPTS_URL, {"ids": ids})
            except Exception as exc:
                log.warning("push receipts unavailable: %s", type(exc).__name__)
                continue
            for ticket_id, item in (body.get("data") or {}).items() if status == 200 else []:
                ok = item.get("status") == "ok"
                found[ticket_id] = (
                    None if ok else str((item.get("details") or {}).get("error") or "error")
                )
        return found


class FakePushSender:
    """For tests: records messages; tokens listed in `errors` get that error kind."""

    def __init__(self, errors: dict[str, str] | None = None) -> None:
        self.sent: list[PushMessage] = []
        self.errors = errors or {}
        self.receipt_errors: dict[str, str] = {}
        self._n = 0

    def send(self, messages: Sequence[PushMessage]) -> list[Ticket]:
        tickets = []
        for message in messages:
            if message.to in self.errors:
                tickets.append(Ticket(message.to, None, self.errors[message.to]))
                continue
            self.sent.append(message)
            self._n += 1
            tickets.append(Ticket(message.to, f"ticket-{self._n}"))
        return tickets

    def receipts(self, ticket_ids: Sequence[str]) -> dict[str, str | None]:
        return {t: self.receipt_errors.get(t) for t in ticket_ids}
