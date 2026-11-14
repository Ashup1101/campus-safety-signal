"""OpenAI Chat Completions client: public news and incident text only, never user data.

The owner's prepaid credits are small, so callers cap every run (`--limit`) and pass a Usage to
count tokens; output is capped per call. A fixed https host, the key from the environment, an
honest User-Agent; errors carry status codes, never request bodies.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from campus_safety.fetch import USER_AGENT

HOST = "https://api.openai.com"
DEFAULT_MODEL = "gpt-4o-mini-2024-07-18"  # dated snapshot: answers stay comparable over time
API_KEY_VAR = "OPENAI_API_KEY"
MAX_OUTPUT_TOKENS = 600
TIMEOUT_SECONDS = 60


class OpenAIError(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, answer: dict[str, Any]) -> None:
        used = answer.get("usage") or {}
        self.calls += 1
        self.prompt_tokens += int(used.get("prompt_tokens", 0))
        self.completion_tokens += int(used.get("completion_tokens", 0))


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL


def api_key() -> str:
    key = os.environ.get(API_KEY_VAR)
    if not key:
        raise OpenAIError(f"{API_KEY_VAR} is not set")
    return key


def generate(
    system: str,
    user: str,
    *,
    model: str | None = None,
    key: str | None = None,
    json_mode: bool = True,
    usage: Usage | None = None,
) -> str:
    """One deterministic answer (temperature 0, fixed seed); JSON mode for extraction."""
    body: dict[str, Any] = {
        "model": model or model_name(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "seed": 3407,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(  # noqa: S310 (fixed https host)
        f"{HOST}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {key or api_key()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            answer = json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise OpenAIError(f"OpenAI returned HTTP {e.code}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise OpenAIError(f"OpenAI request failed: {type(e).__name__}") from e
    if usage is not None:
        usage.add(answer)
    try:
        return str(answer["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise OpenAIError("OpenAI answer had no message content") from e
