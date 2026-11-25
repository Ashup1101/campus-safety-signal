"""Magic-link sign-in for self-service demo accounts: a random 32-byte token sent to the local
mailbox, stored only as its SHA-256 hash, valid for 15 minutes and usable once. A wrong, expired
or used token changes nothing."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from demo_server.store import Store

LIFETIME = timedelta(minutes=15)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(store: Store, account_id: str, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    store.add_magic(_hash(token), account_id, now, now + LIFETIME)
    return token


def redeem(store: Store, token: str, now: datetime) -> str | None:
    digest = _hash(token)
    row = store.magic(digest)
    if row is None or not hmac.compare_digest(row["hash"], digest):
        return None
    if row["used_at"] is not None or now >= row["expires_at"]:
        return None
    return row["account_id"] if store.use_magic(digest, now) else None
