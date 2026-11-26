"""Consents (Sprint 11): what each person agreed to, per feature, with the policy version and the
time. Features that need a consent check it on the server (consent gates)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from demo_server import subscriptions
from demo_server.store import Account, Store

VERSION = (
    "2026-11-draft-1"  # the draft privacy policy these consents refer to (legal review pending)
)
KINDS = ("location_precise", "sharing", "notes", "digests", "briefings")


class Choice(BaseModel):
    granted: bool


def state(row: dict[str, Any] | None) -> str:
    if row is None:
        return "not_asked"
    if row["granted_at"] is None:
        return "declined"
    return "withdrawn" if row["withdrawn_at"] else "granted"


def granted(store: Store, account_id: str, kind: str) -> bool:
    return state(store.consents(account_id).get(kind)) == "granted"


def allowed(store: Store, account: Account, kind: str) -> bool:
    """Built-in demo personas were set up with every consent; accounts people create themselves
    must say yes first."""
    return not account.self_service or granted(store, account.id, kind)


def recipients(store: Store, account_ids: list[str], kind: str) -> list[str]:
    found = []
    for account_id in account_ids:
        account = store.account(account_id)
        if account is not None and allowed(store, account, kind):
            found.append(account_id)
    return found


def register(
    app: FastAPI,
    me: Any,
    store: Store,
    withdrawn: Callable[[Account, str], Awaitable[None]],
) -> None:
    """withdrawn(account, kind) stops a running feature at once (e.g. live sharing)."""
    Me = Annotated[Account, Depends(me)]

    def view(account_id: str) -> list[dict[str, Any]]:
        rows = store.consents(account_id)
        return [
            {
                "kind": kind,
                "state": state(rows.get(kind)),
                "version": rows[kind]["version"] if kind in rows else VERSION,
                "granted_at": rows[kind]["granted_at"] if kind in rows else None,
                "withdrawn_at": rows[kind]["withdrawn_at"] if kind in rows else None,
            }
            for kind in KINDS
        ]

    @app.get("/api/consents")
    def my_consents(who: Me) -> list[dict[str, Any]]:
        return view(who.id)

    @app.post("/api/consents/{kind}")
    async def choose(kind: str, body: Choice, who: Me) -> dict[str, Any]:
        if kind not in KINDS:
            raise HTTPException(404, "unknown consent")
        store.set_consent(who.id, kind, body.granted, VERSION, datetime.now(UTC))
        if not body.granted:
            await withdrawn(who, kind)
        elif kind in subscriptions.KINDS:
            subscriptions.start(store, who, kind)  # double opt-in: a confirm link comes first
        return next(c for c in view(who.id) if c["kind"] == kind)
