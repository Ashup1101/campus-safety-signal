"""Minimal client for a local Ollama server (127.0.0.1 only; nothing leaves the machine)."""

import hashlib
import json
import urllib.request
from typing import Any

HOST = "http://127.0.0.1:11434"
TIMEOUT_SECONDS = 120


class OllamaError(RuntimeError):
    pass


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    # A fixed loopback URL: no outside input chooses the scheme or host.
    request = urllib.request.Request(  # noqa: S310
        f"{HOST}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            answer: dict[str, Any] = json.loads(response.read())
    except OSError as e:
        raise OllamaError(f"Ollama at {HOST} failed: {e}") from e
    return answer


def chat(model: str, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
    """One greedy completion. json_mode asks Ollama to constrain the answer to valid JSON."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "seed": 3407},
    }
    if json_mode:
        body["format"] = "json"
    return str(_post("/api/chat", body).get("message", {}).get("content", ""))


def model_digest(model: str) -> str:
    """A digest of the model's details and Modelfile, so cached outputs name the exact model."""
    info = _post("/api/show", {"model": model})
    details = json.dumps(info.get("details", {}), sort_keys=True) + str(info.get("modelfile", ""))
    return hashlib.sha256(details.encode()).hexdigest()[:16]
