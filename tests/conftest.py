import pytest

from campus_safety.env import DOTENV_VAR


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """CLIs load model keys from .env; tests must never see the owner's real keys."""
    monkeypatch.setenv(DOTENV_VAR, str(tmp_path_factory.getbasetemp() / "no.env"))
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
