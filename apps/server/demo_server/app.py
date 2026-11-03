"""The demo HTTP + WebSocket API. Binds to 127.0.0.1 only; demo logins only (test accounts)."""

import asyncio
import contextlib
import json
import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from campus_safety.lake.storage import open_lake
from campus_safety.official.alerts import OfficialAlertSource
from campus_safety.official.rave import RaveFeedSource
from demo_server import activity
from demo_server.coverage import coverage
from demo_server.hub import Clock, Hub
from demo_server.seed import Settings, seed
from demo_server.sources import DrillSource, ReplaySource, load_replays
from demo_server.store import Account, Store

# The web app runs on 3100 (3000 is often taken by other local projects).
ORIGINS = ["http://localhost:3100", "http://127.0.0.1:3100"]


class Login(BaseModel):
    account_id: str


class Drill(BaseModel):
    action: Literal["drill", "all_clear"]


class ClockPreset(BaseModel):
    preset: Literal["live", "late_night", "event_night"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db)
    seed(store, settings)
    geojson = activity.load_geojson()
    names = {f["properties"]["id"]: f["properties"]["name"] for f in geojson["features"]}
    hub = Hub(store, Clock(), names)
    drills = DrillSource()
    replays = ReplaySource(load_replays(settings.manual))
    sources: list[OfficialAlertSource] = [drills, replays]
    if settings.live_feed:
        sources.append(RaveFeedSource(lake=open_lake(settings.lake_uri)))
    tokens: dict[str, str] = {}

    async def relay(source: OfficialAlertSource) -> None:
        async for alert in source.alerts():
            await hub.publish(alert)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(relay(source)) for source in sources]
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
    app.state.hub, app.state.drills, app.state.replays = hub, drills, replays
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
        return store.alerts(include_test=me.is_test)

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
        return store.latency()

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
