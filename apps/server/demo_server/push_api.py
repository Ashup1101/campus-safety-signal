"""Phones register for push (v14) after the "push" consent; the Expo push token is personal data:
stored server side only, never logged, shown or returned."""

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from demo_server import consents
from demo_server.store import Account, Store

TOKEN = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]{10,64}\]$")
MAX_DEVICES = 5


class Device(BaseModel):
    expo_token: str
    platform: Literal["ios"] = "ios"


class Forget(BaseModel):
    expo_token: str


def register(app: FastAPI, me: Any, store: Store) -> None:
    Me = Annotated[Account, Depends(me)]

    @app.post("/api/devices", status_code=201)
    def add(body: Device, who: Me) -> dict[str, str]:
        if who.role == "console":
            raise HTTPException(403, "the console does not get push")
        if not consents.granted(store, who.id, "push"):
            raise HTTPException(403, "turn on alerts on this phone first")
        if not TOKEN.match(body.expo_token):
            raise HTTPException(400, "not a push token")
        mine = store.devices_of(who.id)
        if body.expo_token not in mine and len(mine) >= MAX_DEVICES:
            raise HTTPException(409, f"up to {MAX_DEVICES} phones; remove one in Settings first")
        store.add_device(body.expo_token, who.id, body.platform, datetime.now(UTC))
        return {"status": "registered"}

    @app.delete("/api/devices", status_code=204)
    def forget(body: Forget, who: Me) -> None:
        store.remove_device(body.expo_token, who.id)
