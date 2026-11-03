"""Demo-only official alert sources: console drills and replays of past nights.

Both reach test accounts only (OfficialAlert.test_only) and always say so in the text: every drill
message starts with "DRILL", every replay message with "RECONSTRUCTION". Replays use IU's real alert
texts and times from data/manual/demo_incidents.yaml, with suspect descriptions removed (a replay
is a history view).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from campus_safety.official.alerts import OfficialAlert, QueueSource
from campus_safety.official.descriptors import strip_descriptors

DRILL_TEXT = "Shelter in place, avoid Kirkwood Avenue."
ALL_CLEAR_TEXT = "All clear. The drill is over."
REPLAY_SPEED = 60.0  # one minute of the real night per second


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DrillSource(QueueSource):
    def __init__(self, now: Callable[[], datetime] = _utc_now) -> None:
        super().__init__("drill", "drill")
        self._now = now

    def drill(self, text: str = DRILL_TEXT) -> None:
        self._push(text, "Severe")

    def all_clear(self) -> None:
        self._push(ALL_CLEAR_TEXT, "Normal")

    def _push(self, text: str, status: str) -> None:
        self.push(
            OfficialAlert(
                source="drill",
                kind="drill",
                text=f"DRILL: {text}",
                verification="drill",
                official_at=self._now(),
                status=status,
            )
        )


@dataclass(frozen=True)
class ReplayStep:
    sent_at: datetime  # local wall time, as IU published it
    status: str
    text: str


@dataclass(frozen=True)
class Replay:
    id: str
    title: str
    summary: str
    sources: tuple[str, ...]
    steps: tuple[ReplayStep, ...]


def load_replays(path: Path) -> dict[str, Replay]:
    if not path.exists():
        return {}
    replays = {}
    for entry in (yaml.safe_load(path.read_text()) or {}).get("incidents", []):
        steps = tuple(
            ReplayStep(a["sent_at"], str(a["status"]), strip_descriptors(str(a["text"])))
            for a in entry.get("alerts", [])
        )
        if steps:
            replays[entry["id"]] = Replay(
                id=str(entry["id"]),
                title=str(entry["title"]),
                summary=str(entry["summary"]),
                sources=tuple(entry.get("sources", [])),
                steps=tuple(sorted(steps, key=lambda s: s.sent_at)),
            )
    return replays


def _sent_label(at: datetime) -> str:
    return f"{at:%b} {at.day}, {at.year}, {at.hour % 12 or 12}:{at:%M %p}"


class ReplaySource(QueueSource):
    def __init__(
        self,
        replays: dict[str, Replay],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        super().__init__("replay", "replay")
        self.replays = replays
        self._sleep = sleep
        self._now = now

    async def play(self, replay_id: str, speed: float = REPLAY_SPEED) -> None:
        replay = self.replays[replay_id]
        previous = replay.steps[0].sent_at
        for index, step in enumerate(replay.steps):
            await self._sleep((step.sent_at - previous).total_seconds() / speed)
            previous = step.sent_at
            self.push(
                OfficialAlert(
                    source="replay",
                    kind="replay",
                    text=f"RECONSTRUCTION (IU alert sent {_sent_label(step.sent_at)}): {step.text}",
                    verification="reconstruction",
                    official_at=self._now(),
                    status=step.status,
                    external_id=f"{replay_id}#{index}",
                    link=replay.sources[0] if replay.sources else None,
                )
            )
