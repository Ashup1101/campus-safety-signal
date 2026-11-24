"""Alert threads: one card per incident.

The first alert of a source opens a thread; later alerts from that source join it while its last
update is under THREAD_GAP old; the source's all-clear word ("Normal") closes it. An all-clear with
no open thread opens and closes its own. Each replay run is its own source (external ids look like
"<replay>:<run>#<step>"), so two plays of one night never share a card.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from campus_safety.official.alerts import OfficialAlert

THREAD_GAP = timedelta(hours=6)
ALL_CLEAR = "normal"


@dataclass
class _Open:
    id: str
    last: datetime


def thread_key(alert: OfficialAlert) -> str:
    if alert.kind == "replay" and alert.external_id:
        return f"replay:{alert.external_id.split('#', 1)[0]}"
    return alert.source


def closes(alert: OfficialAlert) -> bool:
    return alert.status.strip().lower() == ALL_CLEAR


class Threads:
    def __init__(self) -> None:
        self._open: dict[str, _Open] = {}

    def assign(self, alert: OfficialAlert, now: datetime) -> tuple[str, bool]:
        """The thread this alert belongs to, and whether it closes that thread."""
        key = thread_key(alert)
        current = self._open.get(key)
        if current is None or now - current.last > THREAD_GAP:
            current = _Open(uuid.uuid4().hex[:12], now)
            self._open[key] = current
        current.last = now
        if closes(alert):
            del self._open[key]
            return current.id, True
        return current.id, False
