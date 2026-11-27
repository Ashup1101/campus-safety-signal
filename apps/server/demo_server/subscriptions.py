"""Double opt-in and one-click unsubscribe for briefings and digests (Sprint 11). Opting in sends a
confirm link first; nothing else of that kind arrives until it is clicked. Every message carries an
unsubscribe link for its own kind. Each link does one thing only (its token is stored hashed with a
single purpose). Built-in demo personas are treated as confirmed."""

import hashlib
import os
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException

from campus_safety.alerts.rules import Draft
from demo_server.store import Account, Store

KINDS = ("digests", "briefings")
BASE = os.environ.get("DEMO_PUBLIC_URL", "http://localhost:8100")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _link(store: Store, account_id: str, kind: str, purpose: str, base: str) -> str:
    token = secrets.token_urlsafe(24)
    store.add_sub_token(_hash(token), account_id, kind, purpose, datetime.now(UTC))
    return f"{base}/api/subscriptions/{purpose}/{token}"


def start(store: Store, account: Account, kind: str, base: str = BASE, channel: Any = None) -> None:
    """Called when a self-created account opts in: pending until the confirm link is used."""
    if not account.self_service or kind not in KINDS:
        return
    store.set_subscription(account.id, kind, "pending_confirm")
    words = {"digests": "morning digests", "briefings": "event-night briefings"}[kind]
    draft = Draft(
        f"Confirm your {words}",
        f"You asked for {words}. Confirm here to start them: "
        f"{_link(store, account.id, kind, 'confirm', base)}\n"
        "If this was not you, do nothing: you will get none.",
    )
    key = f"confirm:{kind}:{account.id}:{datetime.now(UTC).isoformat()}"
    if channel is not None:  # the mailbox, or real email too (EMAIL_MODE=smtp)
        channel.deliver(account.id, draft, "account", key)
    else:
        store.deliver_mail(key, account.id, "account", draft.title, draft.body)


def active(store: Store, account: Account, kind: str) -> bool:
    return not account.self_service or store.subscription(account.id, kind) == "active"


def recipients(store: Store, account_ids: list[str], kind: str) -> list[str]:
    """People who consented to this kind and confirmed it."""
    from demo_server import consents

    found = []
    for account_id in consents.recipients(store, account_ids, kind):
        account = store.account(account_id)
        if account is not None and active(store, account, kind):
            found.append(account_id)
    return found


def with_unsubscribe(store: Store, account_id: str, kind: str, body: str, base: str = BASE) -> str:
    return f"{body}\n\nStop these messages: {_link(store, account_id, kind, 'unsubscribe', base)}"


def register(app: FastAPI, store: Store) -> None:
    def use(purpose: str, token: str) -> dict[str, Any]:
        found = store.sub_token(_hash(token), purpose)
        if found is None:
            raise HTTPException(404, "this link is not valid")
        state = "active" if purpose == "confirm" else "unsubscribed"
        store.set_subscription(found["account_id"], found["kind"], state)
        return {"state": state}

    @app.get("/api/subscriptions/confirm/{token}")
    def confirm(token: str) -> dict[str, Any]:
        return use("confirm", token)

    @app.get("/api/subscriptions/unsubscribe/{token}")
    def unsubscribe(token: str) -> dict[str, Any]:
        return use("unsubscribe", token)

    @app.post("/api/subscriptions/unsubscribe/{token}")
    def unsubscribe_one_click(token: str) -> dict[str, Any]:
        """Mail apps' one-click unsubscribe (List-Unsubscribe-Post): same single-purpose token."""
        return use("unsubscribe", token)
