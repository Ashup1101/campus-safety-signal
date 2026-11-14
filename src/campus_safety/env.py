"""Model API keys from the gitignored .env, read as KEY=value lines (the file is never sourced
or executed). Only the named keys are read, a key already in the environment wins, and values
are never logged."""

import os
from pathlib import Path

MODEL_KEYS = ("GEMINI_API_KEY", "GEMINI_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL")
DOTENV_VAR = "CAMPUS_SAFETY_DOTENV"  # tests point it at nothing, so real keys never load there


def load_keys(path: Path | None = None, names: tuple[str, ...] = MODEL_KEYS) -> list[str]:
    """Set the named keys that are missing from the environment; returns the names it set."""
    path = path or Path(os.environ.get(DOTENV_VAR, ".env"))
    if not path.is_file():
        return []
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip().strip("\"'")
        if sep and name in names and value:
            found[name] = value
    loaded = [name for name in found if not os.environ.get(name)]
    for name in loaded:
        os.environ[name] = found[name]
    return loaded
