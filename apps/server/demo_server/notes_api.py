"""Community notes API (v9). Students near the area attach a tag (and short text after the
all-clear) to an alert thread; the phone's location is checked in memory and never saved. Parents
read only. Text is filtered server side and never logged; logs carry outcomes only."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from campus_safety.geo.place import distance_to_lines
from campus_safety.notes import filter as text_filter
from campus_safety.notes import rules
from campus_safety.notes.config import NotesConfig
from demo_server.area import area_for
from demo_server.store import Account, Store
from demo_server.threads import THREAD_GAP

log = logging.getLogger(__name__)
LABEL = "Community notes (unverified)"
PSEUDONYM = "IU student nearby"
names_detector: text_filter.Names | None = None  # Presidio on first use; tests set a fake


def _names(text: str) -> list[str]:
    global names_detector
    if names_detector is None:
        names_detector = text_filter.presidio_names()
    return names_detector(text)


class NoteBody(BaseModel):
    tag: str = Field(max_length=60)
    text: str | None = Field(default=None, max_length=500)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


def register(
    app: FastAPI,
    me: Callable[..., Any],
    store: Store,
    geojson: dict[str, Any],
    cfg: NotesConfig,
    event_night: Callable[[], bool],
    changed: Callable[[str], Awaitable[None]],
) -> None:
    """event_night: whether the demo clock is on an event night (3 people instead of 2).
    changed(thread_id): tells every open screen to fetch that thread's notes again."""
    Me = Annotated[Account, Depends(me)]
    names = {f["properties"]["id"]: f["properties"]["name"] for f in geojson["features"]}
    lines = {
        f["properties"]["id"]: tuple(
            tuple((float(x), float(y)) for x, y in line) for line in f["geometry"]["coordinates"]
        )
        for f in geojson["features"]
    }

    def thread_for(thread_id: str, who: Account, now: datetime) -> dict[str, Any]:
        info = store.thread_info(thread_id)
        expired = (
            info
            and info["closed_at"]
            and now - info["closed_at"] > timedelta(hours=cfg.expiry_hours)
        )
        if info is None or expired or (info["test_only"] and not who.is_test):
            raise HTTPException(404, "no such incident")
        return info

    def can_post(student: Account, now: datetime) -> None:
        if student.role != "student":
            raise HTTPException(403, "only students nearby can post")
        if store.setting("notes_enabled", "on") != "on":
            raise HTTPException(403, "notes are switched off")
        if store.banned(student.id, now):
            raise HTTPException(403, "posting is paused for this account")

    def near(info: dict[str, Any], lat: float, lon: float) -> bool:
        area = area_for(info["text"], names)
        return any(distance_to_lines((lon, lat), lines[s]) <= cfg.nearby_m for s in area)

    def save(thread_id: str, body: NoteBody, student: Account) -> dict[str, Any]:
        now = datetime.now(UTC)
        can_post(student, now)
        info = thread_for(thread_id, student, now)
        if not near(info, body.lat, body.lon):  # the point is used here and dropped
            raise HTTPException(400, "not near this area")
        live = info["closed_at"] is None and now - info["last_at"] <= THREAD_GAP
        text = (body.text or "").strip() or None
        refusal = rules.refusal(
            body.tag, text, live=live, all_clear=info["closed_at"] is not None, cfg=cfg
        )
        if refusal:
            raise HTTPException(400, refusal)
        state = "pending"
        if text:
            verdict = text_filter.check(text, cfg, _names)
            if verdict.outcome == "blocked":
                log.info("note text blocked: %s", verdict.reason)
                raise HTTPException(400, verdict.reason)
            if verdict.outcome == "held":
                state = "held"
        note_id = store.put_note(thread_id, student.id, body.tag, text, state, now)
        log.info("note saved as %s", state)
        return {"id": note_id, "state": state}

    @app.post("/api/threads/{thread_id}/note", status_code=201)
    async def post_note(thread_id: str, body: NoteBody, student: Me) -> dict[str, Any]:
        saved = save(thread_id, body, student)
        await changed(thread_id)
        return saved

    @app.put("/api/threads/{thread_id}/note")
    async def edit_note(thread_id: str, body: NoteBody, student: Me) -> dict[str, Any]:
        if not any(n["account_id"] == student.id for n in store.notes_of(thread_id)):
            raise HTTPException(404, "no note to edit")
        saved = save(thread_id, body, student)
        await changed(thread_id)
        return saved

    @app.delete("/api/threads/{thread_id}/note", status_code=204)
    async def withdraw_note(thread_id: str, student: Me) -> Response:
        mine = [n for n in store.notes_of(thread_id) if n["account_id"] == student.id]
        if not mine:
            raise HTTPException(404, "no note to withdraw")
        store.delete_note(int(mine[0]["id"]))
        log.info("note withdrawn")
        await changed(thread_id)
        return Response(status_code=204)

    @app.get("/api/threads/{thread_id}/notes")
    def read_notes(thread_id: str, who: Me) -> dict[str, Any]:
        """Confirmed notes only, with no account named; the reader's own note (any state)."""
        thread_for(thread_id, who, datetime.now(UTC))
        notes = store.notes_of(thread_id)
        enabled = store.setting("notes_enabled", "on") == "on"
        shown = rules.corroborated(notes, event_night=event_night(), cfg=cfg) if enabled else []
        mine = next((n for n in notes if n["account_id"] == who.id), None)
        return {
            "label": LABEL,
            "notes": [{**s, "by": PSEUDONYM} for s in shown],
            "mine": {k: mine[k] for k in ("tag", "text", "state")} if mine else None,
            "enabled": enabled,
        }
