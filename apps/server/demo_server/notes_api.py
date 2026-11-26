"""Community notes API (v9). Students near the area attach a tag (and short text after the
all-clear) to an alert thread; the phone's location is checked in memory and never saved. Parents
read only. Text is filtered server side and never logged; logs carry outcomes only."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

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
BAN_LENGTH = timedelta(days=7)
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
    console: Callable[..., Any],
    store: Store,
    geojson: dict[str, Any],
    cfg: NotesConfig,
    event_night: Callable[[], bool],
    changed: Callable[[str], Awaitable[None]],
) -> None:
    """event_night: whether the demo clock is on an event night (3 people instead of 2).
    changed(thread_id): tells every open screen to fetch that thread's notes again."""
    Me = Annotated[Account, Depends(me)]
    Console = Annotated[Any, Depends(console)]
    names = {f["properties"]["id"]: f["properties"]["name"] for f in geojson["features"]}
    lines = {
        f["properties"]["id"]: tuple(
            tuple((float(x), float(y)) for x, y in line) for line in f["geometry"]["coordinates"]
        )
        for f in geojson["features"]
    }

    def thread_for(thread_id: str, who: Account, now: datetime) -> dict[str, Any]:
        info = store.thread_info(thread_id)
        # Closed by IU's all-clear, or gone quiet (THREAD_GAP): the same rule as expire_notes.
        closed = info and (info["closed_at"] or info["last_at"] + THREAD_GAP)
        expired = closed and now - closed > timedelta(hours=cfg.expiry_hours)
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
        # The filter may load Presidio: never on the event loop that relays alerts.
        saved = await run_in_threadpool(save, thread_id, body, student)
        await changed(thread_id)
        return saved

    @app.put("/api/threads/{thread_id}/note")
    async def edit_note(thread_id: str, body: NoteBody, student: Me) -> dict[str, Any]:
        if not any(n["account_id"] == student.id for n in store.notes_of(thread_id)):
            raise HTTPException(404, "no note to edit")
        saved = await run_in_threadpool(save, thread_id, body, student)
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

    @app.post("/api/notes/{note_id}/report")
    async def report_note(note_id: int, who: Me) -> dict[str, bool]:
        """Any reader may report a note once; enough reports hide it until a moderator looks."""
        note = store.note(note_id)
        if note is None:
            raise HTTPException(404, "no such note")
        thread_for(str(note["thread_id"]), who, datetime.now(UTC))
        if note["account_id"] == who.id:
            raise HTTPException(400, "you cannot report your own note")
        if not store.add_report(note_id, who.id):
            raise HTTPException(409, "already reported")
        hidden = store.report_count(note_id) >= cfg.report_threshold
        if hidden and note["state"] in ("pending", "visible"):
            store.set_note_state(note_id, "hidden")
            log.info("note hidden by reports")
            await changed(str(note["thread_id"]))
        return {"hidden": hidden}

    @app.get("/api/notes/config")
    def notes_settings(_: Me) -> dict[str, Any]:
        """What the composer offers: tags, the live-alert and after-all-clear subsets, text size."""
        return {
            "tags": list(cfg.tags),
            "safety_tags": list(cfg.safety_tags),
            "after_all_clear_tags": list(cfg.after_all_clear_tags),
            "text_limit": cfg.text_limit,
        }

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

    # Moderation (console only): act on a note; the console never sees who posted it.
    def moderated(note_id: int) -> dict[str, Any]:
        note = store.note(note_id)
        if note is None:
            raise HTTPException(404, "no such note")
        return note

    @app.get("/api/console/notes/queue")
    def notes_queue(_: Console) -> list[dict[str, Any]]:
        """Held (alarming words) and hidden (reports or a moderator) notes, oldest first."""
        queue = store.notes_in("held") + store.notes_in("hidden")
        return [
            {
                "id": n["id"],
                "thread_id": n["thread_id"],
                "tag": n["tag"],
                "text": n["text"],
                "state": n["state"],
                "reports": store.report_count(int(n["id"])),
                "created_at": n["created_at"],
            }
            for n in sorted(queue, key=lambda n: int(n["id"]))
        ]

    @app.post("/api/console/notes/{note_id}/{action}")
    async def moderate(note_id: int, action: str, _: Console) -> dict[str, str]:
        note = moderated(note_id)
        thread_id = str(note["thread_id"])
        if action == "hide":
            store.set_note_state(note_id, "hidden")
        elif action == "unhide":
            store.set_note_state(note_id, "pending")  # counts toward corroboration again
        elif action == "ban":
            store.ban(str(note["account_id"]), datetime.now(UTC) + BAN_LENGTH)
            store.delete_notes(account_id=str(note["account_id"]))
        else:
            raise HTTPException(404, "unknown action")
        log.info("moderator %s", action)
        await changed(thread_id)
        return {"done": action}

    class Switch(BaseModel):
        enabled: bool

    @app.get("/api/console/notes/switch")
    def notes_switch(_: Console) -> dict[str, bool]:
        return {"enabled": store.setting("notes_enabled", "on") == "on"}

    @app.post("/api/console/notes/switch")
    async def set_notes_switch(body: Switch, _: Console) -> dict[str, bool]:
        """IU's kill switch: off hides every note and blocks posting at once; on restores them."""
        store.set_setting("notes_enabled", "on" if body.enabled else "off")
        log.info("notes switched %s", "on" if body.enabled else "off")
        await changed("*")
        return {"enabled": body.enabled}
