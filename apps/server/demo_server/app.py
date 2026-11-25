"""The demo HTTP + WebSocket API. Binds to 127.0.0.1 only; demo logins only (test accounts)."""

import asyncio
import contextlib
import json
import re
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from campus_safety import events
from campus_safety.alerts.rules import Draft
from campus_safety.lake.storage import open_lake
from campus_safety.official.alerts import OfficialAlertSource
from campus_safety.official.rave import RaveFeedSource
from demo_server import activity, auth, points, tonight_model
from demo_server.area import area_for
from demo_server.coverage import coverage
from demo_server.hub import Clock, Hub
from demo_server.mailbox import MailboxChannel
from demo_server.scheduler import Scheduler
from demo_server.seed import Settings, seed
from demo_server.sources import DrillSource, ReplaySource, load_replays
from demo_server.store import Account, Store

# The web app runs on 3100 (3000 is often taken by other local projects).
ORIGINS = ["http://localhost:3100", "http://127.0.0.1:3100"]


class Login(BaseModel):
    account_id: str


class Drill(BaseModel):
    action: Literal["drill", "all_clear"]


class Signup(BaseModel):
    email: str
    role: Literal["student", "parent"]
    display_name: str


class Signin(BaseModel):
    email: str


EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
LINKS_PER_HOUR = 5
WEB = "http://localhost:3100"


class Invite(BaseModel):
    student_email: str


class ClockPreset(BaseModel):
    preset: Literal["live", "late_night", "event_night"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db)
    geojson = activity.load_segments(settings.warehouse)  # one read: names and levels agree
    seed(store, settings, geojson=geojson)
    names = {f["properties"]["id"]: f["properties"]["name"] for f in geojson["features"]}
    hub = Hub(store, Clock(), names)
    scheduler = Scheduler(
        store, MailboxChannel(store), settings.warehouse, names, events.load(), hub.clock.now
    )
    drills = DrillSource()
    replays = ReplaySource(load_replays(settings.manual))
    sources: list[OfficialAlertSource] = [drills, replays]
    watcher = RaveFeedSource(lake=open_lake(settings.lake_uri)) if settings.live_feed else None
    if watcher is not None:
        sources.append(watcher)
    tokens: dict[str, str] = {}

    async def relay(source: OfficialAlertSource) -> None:
        async for alert in source.alerts():
            await hub.publish(alert)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(relay(source)) for source in sources]
        tasks.append(asyncio.create_task(scheduler.run()))
        yield
        for task in tasks:
            task.cancel()
        store.close()

    app = FastAPI(title="campus-safety-signal demo", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=2048)  # ~1,300 generated segments
    app.state.hub, app.state.drills, app.state.replays = hub, drills, replays
    app.state.store = store
    app.mount("/tiles", StaticFiles(directory=settings.tiles, check_dir=False), name="tiles")

    def account_for(token: str | None) -> Account | None:
        account_id = tokens.get(token or "")
        return store.account(account_id) if account_id else None

    def current(authorization: Annotated[str | None, Header()] = None) -> Account:
        scheme, _, token = (authorization or "").partition(" ")
        account = account_for(token) if scheme.lower() == "bearer" else None
        if account is None:
            raise HTTPException(401, "log in first")
        return account

    def console(account: Annotated[Account, Depends(current)]) -> Account:
        if account.role != "console":
            raise HTTPException(403, "console only")
        return account

    Me = Annotated[Account, Depends(current)]
    Console = Annotated[Account, Depends(console)]

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def send_link(account: Account) -> bool:
        """A sign-in link to the account's mailbox, at most LINKS_PER_HOUR an hour."""
        now = datetime.now(UTC)
        if store.magic_issued_since(account.id, now - timedelta(hours=1)) >= LINKS_PER_HOUR:
            return False
        token = auth.issue(store, account.id, now)
        body = (
            f"Open {WEB}/magic/{token} within 15 minutes to sign in. It works once."
            " If you did not ask for this, ignore it."
        )
        MailboxChannel(store).deliver(
            account.id, Draft("Your sign-in link", body), "account", token
        )
        return True

    @app.post("/api/signup", status_code=202)
    def signup(body: Signup) -> dict[str, str]:
        email, name = body.email.strip().lower(), body.display_name.strip()
        if not EMAIL.match(email) or len(email) > 254 or not 1 <= len(name) <= 40:
            raise HTTPException(400, "check the email and the name (1 to 40 characters)")
        if store.account_by_email(email):
            raise HTTPException(409, "an account already uses this email; sign in instead")
        account = Account(
            f"{body.role}_{secrets.token_hex(4)}", body.role, name, False, email, True
        )
        store.add_account(account)
        send_link(account)
        return {"status": "sent"}

    @app.post("/api/signin", status_code=202)
    def signin(body: Signin) -> dict[str, str]:
        # The same answer whether or not the address has an account (no account lookup by email).
        account = store.account_by_email(body.email)
        if account is not None and not send_link(account):
            raise HTTPException(429, "too many sign-in links; try again in an hour")
        return {"status": "sent"}

    @app.get("/api/magic/{token}")
    def magic(token: str) -> dict[str, Any]:
        account_id = auth.redeem(store, token, datetime.now(UTC))
        account = store.account(account_id) if account_id else None
        if account is None:
            raise HTTPException(400, "this sign-in link is not valid any more; ask for a new one")
        bearer = secrets.token_urlsafe(24)
        tokens[bearer] = account.id
        return {
            "token": bearer,
            "account": {"id": account.id, "role": account.role, "name": account.display_name},
        }

    @app.post("/api/invites", status_code=201)
    def invite(body: Invite, me: Me) -> dict[str, object]:
        if me.role != "parent":
            raise HTTPException(403, "only parents send invites")
        email = body.student_email.strip().lower()
        if not EMAIL.match(email):
            raise HTTPException(400, "check the student's email")
        invite_id = store.add_invite(me.id, email, datetime.now(UTC))
        if invite_id is None:
            raise HTTPException(409, "an invite to this student is already waiting")
        return {"id": invite_id, "status": "pending"}

    @app.post("/api/invites/{invite_id}/{answer}")
    def answer_invite(
        invite_id: int, answer: Literal["accept", "decline"], me: Me
    ) -> dict[str, str]:
        parent_id = store.answer_invite(invite_id, me, answer == "accept", datetime.now(UTC))
        if parent_id is None:
            raise HTTPException(404, "no waiting invite like that for you")
        return {"status": "accepted" if answer == "accept" else "declined"}

    @app.delete("/api/links/{other_id}", status_code=204)
    def unlink(other_id: str, me: Me) -> None:
        parent_id, student_id = (other_id, me.id) if me.role == "student" else (me.id, other_id)
        if not store.unlink(parent_id, student_id):
            raise HTTPException(404, "no link like that")
        other = store.account(other_id)
        if other is not None:  # one gentle notice to the other side, in their mailbox
            notice = Draft(
                f"{me.display_name} unlinked", f"{me.display_name} is no longer linked with you."
            )
            key = f"unlink:{parent_id}:{student_id}:{secrets.token_hex(4)}"
            MailboxChannel(store).deliver(other.id, notice, "account", key)

    @app.get("/api/invites")
    def invites(me: Me) -> list[dict[str, Any]]:
        return store.invites(me, datetime.now(UTC))

    @app.get("/api/accounts")
    def accounts() -> list[dict[str, str]]:
        return [{"id": a.id, "role": a.role, "name": a.display_name} for a in store.accounts()]

    @app.post("/api/login")
    def login(body: Login) -> dict[str, Any]:
        account = store.account(body.account_id)
        if account is None or not account.is_test:
            raise HTTPException(404, "no such demo account")
        token = secrets.token_urlsafe(24)
        tokens[token] = account.id
        return {
            "token": token,
            "account": {"id": account.id, "role": account.role, "name": account.display_name},
        }

    @app.get("/api/alerts")
    def alerts(me: Me) -> list[dict[str, object]]:
        rows = store.alerts(include_test=me.is_test)
        return [{**row, "area": area_for(str(row["text"]), names)} for row in rows]

    @app.get("/api/zones")
    def zones(me: Me) -> list[dict[str, object]]:
        return [vars(z) for z in store.zones(me.id)]

    @app.get("/api/segments")
    def segments(_: Me) -> dict[str, Any]:
        levels: dict[str, dict[str, dict[str, str]]] = {}
        for row in store.activity():
            levels.setdefault(row.segment_id, {})[row.window] = {
                "level": row.level,
                "reason": row.reason,
            }
        features = [
            {
                **f,
                "properties": {
                    "id": f["properties"]["id"],
                    "name": f["properties"]["name"],
                    "levels": levels.get(f["properties"]["id"], {}),
                },
            }
            for f in geojson["features"]
        ]
        return {
            "type": "FeatureCollection",
            "features": features,
            "attribution": geojson["attribution"],
            "clock": hub.clock.state(),
        }

    @app.get("/api/incidents")
    def incident_points(_: Me, days: Annotated[int, Query(ge=1, le=1095)] = 90) -> dict[str, Any]:
        return points.recent(settings.warehouse, days, date.today())

    @app.get("/api/watcher")
    def watcher_health(_: Console) -> dict[str, object]:
        schedule = scheduler.upcoming()
        if watcher is None:
            return {"enabled": False, **schedule}
        return {"enabled": True, **watcher.health.as_dict(), **schedule}

    @app.get("/api/mailbox")
    def mailbox(me: Me) -> list[dict[str, object]]:
        return store.mailbox(me.id)

    @app.get("/api/tonight-model")
    def tonight_model_card(_: Console) -> dict[str, Any]:
        return tonight_model.card(settings.lake_uri)

    @app.get("/api/clock")
    def get_clock() -> dict[str, Any]:
        return hub.clock.state()

    @app.post("/api/clock")
    async def set_clock(body: ClockPreset, _: Console) -> dict[str, Any]:
        return await hub.set_clock(body.preset)

    @app.get("/api/coverage")
    def data_coverage(_: Me) -> dict[str, Any]:
        return coverage(settings.warehouse, settings.gaps)

    @app.post("/api/drill")
    def drill(body: Drill, _: Console) -> dict[str, str]:
        drills.drill() if body.action == "drill" else drills.all_clear()
        return {"status": "sent"}

    @app.get("/api/replays")
    def list_replays(_: Console) -> list[dict[str, object]]:
        return [
            {
                "id": r.id,
                "title": r.title,
                "summary": r.summary,
                "sources": list(r.sources),
                "alerts": len(r.steps),
                "first": r.steps[0].sent_at.isoformat(),
            }
            for r in replays.replays.values()
        ]

    @app.post("/api/replays/{replay_id}")
    async def play(replay_id: str, _: Console) -> dict[str, str]:
        if replay_id not in replays.replays:
            raise HTTPException(404, "no such replay")
        asyncio.get_running_loop().create_task(replays.play(replay_id, settings.replay_speed))
        return {"status": "playing"}

    @app.get("/api/latency")
    def latency(_: Console) -> list[dict[str, object]]:
        # Check-ins are counted, never shown: no names, states or places reach the console.
        rows = store.latency()
        return [{**row, "check_ins": len(hub.check_ins(str(row["thread_id"])))} for row in rows]

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str = "") -> None:
        account = account_for(token)
        if account is None:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        await hub.join(account, websocket)
        try:
            while True:
                try:
                    data = json.loads(await websocket.receive_text())
                except ValueError:
                    continue
                if isinstance(data, dict):
                    await hub.message(account, data)
        except WebSocketDisconnect:
            pass
        finally:
            await hub.leave(account, websocket)

    return app
