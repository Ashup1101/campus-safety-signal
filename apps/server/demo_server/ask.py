"""Ask: questions about past incidents answered from the public-data index with numbered
citations (campus_safety.rag). The model is chosen by DEMO_ASK_PROVIDER (gemini | openai); unset
or "none" calls no model and lists the matching records with their citations instead. Questions
about people or sensitive cases and instruction-like text are refused (the rag agent's screen).
Retrieved text is data, never instructions."""

import os
from datetime import date
from pathlib import Path
from typing import Any

from campus_safety.env import load_keys
from campus_safety.news import providers
from campus_safety.rag.graph import Agent
from campus_safety.rag.index import Index

DAILY = 20
NO_MODEL = "No AI answer available here: these are the matching records."


def provider() -> str:
    return os.environ.get("DEMO_ASK_PROVIDER", "none").strip().lower()


def _generator(name: str) -> Any:
    if name in providers.PROVIDERS:
        load_keys()
        return providers.generator(name, providers.default_model(name), json_mode=False)
    return lambda system, user: ""  # no model: the agent falls back to the matching records


def answer(index_path: Path, question: str, today: date) -> dict[str, Any]:
    """Raises FileNotFoundError when the index has not been built."""
    idx = Index(index_path)
    name = provider()
    try:
        try:
            state = Agent(idx, _generator(name)).ask(question, today)
        except providers.ERRORS:
            state = Agent(idx, _generator("none")).ask(question, today)
    finally:
        idx.close()
    ai = bool(state.get("draft")) and not state.get("problems") and not state.get("refused")
    found = {"answer": state["answer"], "citations": state.get("citations", []), "ai": ai}
    if not ai and found["citations"]:
        found["notice"] = NO_MODEL
    return found
