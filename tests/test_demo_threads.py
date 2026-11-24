"""Alert threads: one card per incident. Made-up sources and texts."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from campus_safety.official.alerts import OfficialAlert
from demo_server.hub import Clock, Hub
from demo_server.seed import ACCOUNTS
from demo_server.sources import DrillSource
from demo_server.store import Store
from demo_server.threads import Threads

T0 = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)


def alert(
    status: str = "Severe", source: str = "feed", external_id: str | None = None
) -> OfficialAlert:
    replay = source == "replay"
    return OfficialAlert(
        source=source,
        kind="replay" if replay else "web_page",
        text="Made-up alert.",
        verification="reconstruction" if replay else "official",
        official_at=T0,
        status=status,
        external_id=external_id,
    )


def test_updates_join_and_the_all_clear_closes_the_thread() -> None:
    threads = Threads()
    first, closed1 = threads.assign(alert(), T0)
    second, closed2 = threads.assign(alert(), T0 + timedelta(minutes=20))
    third, closed3 = threads.assign(alert("Normal"), T0 + timedelta(minutes=40))
    after, _ = threads.assign(alert(), T0 + timedelta(minutes=50))
    assert first == second == third
    assert (closed1, closed2, closed3) == (False, False, True)
    assert after != first  # closed: the next alert opens a new thread


def test_six_quiet_hours_start_a_new_thread() -> None:
    threads = Threads()
    first, _ = threads.assign(alert(), T0)
    late, _ = threads.assign(alert(), T0 + timedelta(hours=6, seconds=1))
    assert late != first


def test_an_all_clear_without_an_open_thread_opens_and_closes_its_own() -> None:
    threads = Threads()
    thread, closed = threads.assign(alert("Normal"), T0)
    assert closed
    assert threads.assign(alert(), T0 + timedelta(minutes=1))[0] != thread


def test_sources_and_replay_runs_never_share_a_thread() -> None:
    threads = Threads()
    feed, _ = threads.assign(alert(), T0)
    drill, _ = threads.assign(alert(source="drill"), T0)
    run1, _ = threads.assign(alert(source="replay", external_id="night:1#0"), T0)
    run1b, _ = threads.assign(alert(source="replay", external_id="night:1#1"), T0)
    run2, _ = threads.assign(alert(source="replay", external_id="night:2#0"), T0)
    assert len({feed, drill, run1, run2}) == 4
    assert run1 == run1b


def test_store_keeps_the_thread_and_upgrades_old_databases(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite3"
    with sqlite3.connect(path) as db:  # a database from before threads existed
        db.execute(
            "create table alerts (id text primary key, source text not null, kind text not null,"
            " status text not null, verification text not null, test_only integer not null,"
            " official_at text, received_at text not null, stored_text text not null, link text)"
        )
        db.execute(
            "insert into alerts values ('old1', 'feed', 'web_page', 'Severe', 'official', 0,"
            " null, '2026-10-01T00:00:00+00:00', 'Old.', null)"
        )
    store = Store(path)
    store.add_alert("new1", alert(), T0, thread_id="thr1")
    rows = {r["id"]: r["thread_id"] for r in store.alerts(include_test=True)}
    assert rows == {"old1": "old1", "new1": "thr1"}


class Peer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: Any, mode: str = "text") -> None:
        self.sent.append(data)


def test_hub_sends_the_drill_and_its_all_clear_on_one_thread(tmp_path: Path) -> None:
    store = Store(tmp_path / "demo.sqlite3")
    for account in ACCOUNTS:
        store.add_account(account)

    async def scenario() -> Peer:
        hub, peer, drills = Hub(store, Clock(), {}), Peer(), DrillSource()
        await hub.join(ACCOUNTS[0], peer)
        drills.drill()
        drills.all_clear()
        stream = drills.alerts()
        for _ in range(2):
            await hub.publish(await anext(stream))
        return peer

    alerts = [m["alert"] for m in asyncio.run(scenario()).sent if m["type"] == "alert"]
    assert alerts[0]["thread_id"] == alerts[1]["thread_id"]
    assert [a["closed"] for a in alerts] == [False, True]
    stored = {r["thread_id"] for r in store.alerts(include_test=True)}
    assert stored == {alerts[0]["thread_id"]}
