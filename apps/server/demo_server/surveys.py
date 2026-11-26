"""Short pilot surveys (Sprint 11): three 1-5 questions after sign-up and a day after an alert card
the person received closes. Answers are numbers only (no free text, so no personal data); each
prompt is answered or skipped once."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from demo_server.store import Account, Store
from demo_server.threads import THREAD_GAP

QUESTIONS = {
    "signup": (
        "Setting up was easy.",
        "I understand what the app shares and what it never keeps.",
        "I feel in control of who sees my information.",
    ),
    "after_alert": (
        "The alert reached me quickly.",
        "The alert was clear about what to do.",
        "I trusted the information in the app.",
    ),
}
AFTER = timedelta(hours=24)  # ask a day after the card closes
WINDOW = timedelta(days=7)  # and not after a week


class Answer(BaseModel):
    answers: list[Annotated[int, Field(ge=1, le=5)]] | None = None
    skip: bool = False

    @model_validator(mode="after")
    def three_or_skip(self) -> "Answer":
        if not self.skip and (self.answers is None or len(self.answers) != 3):
            raise ValueError("three answers from 1 to 5, or skip")
        return self


def due(store: Store, account: Account, now: datetime) -> list[dict[str, Any]]:
    done = store.survey_prompts(account.id)
    prompts = [] if "signup" in done else ["signup"]
    for thread_id in store.threads_delivered_to(account.id):
        info = store.thread_info(thread_id)
        closed = info and (info["closed_at"] or info["last_at"] + THREAD_GAP)
        if closed and AFTER <= now - closed <= WINDOW and f"after_alert:{thread_id}" not in done:
            prompts.append(f"after_alert:{thread_id}")
    return [{"prompt": p, "questions": list(QUESTIONS[p.split(":")[0]])} for p in prompts]


def register(app: FastAPI, me: Any, store: Store) -> None:
    Me = Annotated[Account, Depends(me)]

    @app.get("/api/surveys/due")
    def surveys_due(who: Me) -> list[dict[str, Any]]:
        return due(store, who, datetime.now(UTC))

    @app.post("/api/surveys/{prompt}", status_code=201)
    def answer(prompt: str, body: Answer, who: Me) -> dict[str, str]:
        if prompt not in {d["prompt"] for d in due(store, who, datetime.now(UTC))}:
            already = prompt in store.survey_prompts(who.id)
            raise HTTPException(
                409 if already else 404, "already answered" if already else "no such survey"
            )
        store.add_survey_answer(
            who.id, prompt, None if body.skip else body.answers, datetime.now(UTC)
        )
        return {"state": "skipped" if body.skip else "answered"}
