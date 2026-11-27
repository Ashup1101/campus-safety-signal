"""Background sessions (v15): while Share until I'm home or a heads-up session runs, the phone
checks its own location and sends only events: started, ended (with the reason), heads_up (a street
id) and arrived_home. Coordinates are refused outright; nothing is stored; the console sees counts
only."""

import asyncio
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from demo_server import consents
from demo_server.store import Account, Store


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")  # lat, lon or anything else: 422

    session_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,40}$")]
    kind: Literal["started", "ended", "heads_up", "arrived_home"]
    segment_id: Annotated[str, Field(max_length=80)] | None = None
    reason: Literal["arrived", "timeout", "low_battery", "turned_off"] | None = None


class Sessions:
    """Running sessions in memory only (session id -> student, events already relayed)."""

    def __init__(self) -> None:
        self.owner: dict[str, str] = {}
        self.relayed: dict[str, set[str]] = {}
        self.counts: Counter[str] = Counter()


def register(app: FastAPI, me: Any, store: Store, hub: Any, console: Any) -> Sessions:
    Me = Annotated[Account, Depends(me)]
    Console = Annotated[Account, Depends(console)]
    sessions = Sessions()

    @app.get("/api/console/sessions")
    def counts(_: Console) -> dict[str, Any]:
        """Sessions running, started, ended by reason, and events relayed: numbers only."""
        return {"running": len(sessions.owner), **dict(sessions.counts)}

    @app.post("/api/sessions/events", status_code=202)
    async def event(body: SessionEvent, who: Me) -> dict[str, str]:
        if who.role != "student":
            raise HTTPException(403, "sessions are for students")
        if not consents.allowed(store, who, "background_location"):
            raise HTTPException(403, "turn on location while the app is closed first")
        if body.kind == "started":
            sessions.owner[body.session_id] = who.id
            sessions.relayed[body.session_id] = set()
            sessions.counts["started"] += 1
            return {"status": "ok"}
        if sessions.owner.get(body.session_id) != who.id:
            raise HTTPException(404, "no running session like that")
        if body.kind == "ended":
            sessions.owner.pop(body.session_id, None)
            sessions.relayed.pop(body.session_id, None)
            sessions.counts[f"ended_{body.reason or 'turned_off'}"] += 1
            return {"status": "ok"}
        done = sessions.relayed[body.session_id]
        tag = body.kind if body.kind == "arrived_home" else f"heads_up:{body.segment_id}"
        if tag in done:
            return {"status": "already sent"}
        if body.kind == "heads_up":
            name = hub.segment_name(body.segment_id or "")
            if name is None:
                raise HTTPException(400, "unknown street")
            message: dict[str, Any] = {
                "type": "heads_up",
                "student_id": who.id,
                "student_name": who.display_name,
                "segment_id": body.segment_id,
                "segment_name": name,
            }
        else:
            message = {
                "type": "arrived_home",
                "student_id": who.id,
                "student_name": who.display_name,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        done.add(tag)
        sessions.counts[body.kind] += 1
        await hub.to_parents(who.id, message)
        if hub.push is not None:  # parents whose app is closed: by push, street name only
            if body.kind == "arrived_home":
                title, words = f"{who.display_name} arrived home", "Share until I'm home has ended."
            else:
                title = f"Heads-up: {who.display_name}"
                words = f"{who.display_name} is on {message['segment_name']}, which is busier now."
            await asyncio.to_thread(
                hub.push.deliver,
                f"push:session:{body.session_id}:{tag}",
                list(store.parents_of(who.id)),
                title,
                words,
                {"student_id": who.id},
            )
        return {"status": "ok"}

    return sessions
