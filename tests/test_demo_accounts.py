"""Demo accounts: email and self-service fields, and upgrading an older demo database."""

import sqlite3
from pathlib import Path

import pytest

from demo_server.store import Account, Store


def test_an_older_database_upgrades_and_keeps_its_accounts(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite3"
    with sqlite3.connect(path) as old:
        old.execute(
            "create table accounts (id text primary key, role text not null, display_name text"
            " not null, is_test integer not null)"
        )
        old.execute("insert into accounts values ('parent_mom', 'parent', 'Mom', 1)")
    store = Store(path)
    assert store.account("parent_mom") == Account("parent_mom", "parent", "Mom", True)
    store.add_account(
        Account("p1", "parent", "Pat", False, email="pat@example.test", self_service=True)
    )
    assert store.account("p1") == Account("p1", "parent", "Pat", False, "pat@example.test", True)
    assert store.account_by_email("PAT@example.test") == store.account("p1")


def test_one_account_per_email(tmp_path: Path) -> None:
    store = Store(tmp_path / "demo.sqlite3")
    store.add_account(Account("a", "parent", "A", False, email="same@example.test"))
    with pytest.raises(sqlite3.IntegrityError):
        store.add_account(Account("b", "student", "B", False, email="same@example.test"))
