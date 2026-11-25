"""Magic-link sign-in tokens: random, stored hashed, short-lived, single use."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from demo_server import auth
from demo_server.store import Account, Store

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "demo.sqlite3")
    store.add_account(
        Account("p1", "parent", "Pat", False, email="pat@example.test", self_service=True)
    )
    return store


def test_a_token_signs_in_once_within_15_minutes(store: Store) -> None:
    token = auth.issue(store, "p1", NOW)
    assert len(token) >= 40 and token not in str(store.magic_rows())  # only the hash is stored
    assert auth.redeem(store, token, NOW + timedelta(minutes=14)) == "p1"
    assert auth.redeem(store, token, NOW + timedelta(minutes=14)) is None  # single use


def test_expired_unknown_or_tampered_tokens_change_nothing(store: Store) -> None:
    token = auth.issue(store, "p1", NOW)
    assert auth.redeem(store, token, NOW + timedelta(minutes=16)) is None
    assert auth.redeem(store, "not-a-token", NOW) is None
    assert auth.redeem(store, token[:-1] + ("A" if token[-1] != "A" else "B"), NOW) is None
    fresh = auth.issue(store, "p1", NOW)
    assert auth.redeem(store, fresh, NOW) == "p1"  # earlier failures left it untouched
