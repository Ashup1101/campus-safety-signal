"""The demo API runs sync handlers in a thread pool: the store is used from many threads."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from demo_target import store_at

from demo_server.seed import ACCOUNTS
from demo_server.store import Store


def test_parallel_lookups_never_lose_an_account(tmp_path: Path) -> None:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)
    ids = [a.id for a in ACCOUNTS] * 200

    def lookup(account_id: str) -> bool:
        store.alerts(include_test=True)
        return store.account(account_id) is not None

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lookup, ids))
    assert all(results)


def test_parallel_sends_of_one_key_deliver_exactly_one_message(tmp_path: Path) -> None:
    store = Store(store_at(tmp_path))
    for account in ACCOUNTS:
        store.add_account(account)

    def send(_: int) -> bool:
        return store.deliver_mail(
            "digest:student_sam:2026-11-26", "student_sam", "digest", "s", "b"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(40)))
    assert results.count(True) == 1
    assert len(store.mailbox("student_sam")) == 1
