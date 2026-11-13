"""Gemini API client for extraction: public news text only, never user data.

A fixed https host, the key from the environment (SSM later), an honest User-Agent, JSON-mode
answers. No robots check: this is an API call to a service we are signed up for, not a crawl.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

from campus_safety.fetch import USER_AGENT

HOST = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_SECONDS = 60
API_KEY_VAR = "GEMINI_API_KEY"


class GeminiError(RuntimeError):
    pass


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def api_key() -> str:
    key = os.environ.get(API_KEY_VAR)
    if not key:
        raise GeminiError(f"{API_KEY_VAR} is not set")
    return key


def generate(system: str, user: str, *, model: str | None = None, key: str | None = None) -> str:
    """One deterministic JSON-mode answer. Errors carry status codes, never the request body."""
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    request = urllib.request.Request(  # noqa: S310 (fixed https host)
        f"{HOST}/v1beta/models/{model or model_name()}:generateContent",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-goog-api-key": key or api_key(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            answer = json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise GeminiError(f"Gemini returned HTTP {e.code}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise GeminiError(f"Gemini request failed: {type(e).__name__}") from e
    try:
        return str(answer["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError) as e:
        raise GeminiError("Gemini answer had no text part") from e
