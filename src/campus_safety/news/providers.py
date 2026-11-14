"""Which model answers: Gemini (free tier, the default) or OpenAI (the owner's small prepaid
credits). Both see public news and incident text only. A generator is bound to one model, so
the model named in the cache key is the model that answered.
"""

from collections.abc import Callable

from campus_safety.news import gemini, openai_api

Generate = Callable[[str, str], str]
PROVIDERS = ("gemini", "openai")
ERRORS: tuple[type[Exception], ...] = (gemini.GeminiError, openai_api.OpenAIError)


def default_model(provider: str) -> str:
    return openai_api.model_name() if provider == "openai" else gemini.model_name()


def generator(
    provider: str, model: str, *, json_mode: bool, usage: openai_api.Usage | None = None
) -> Generate:
    if provider == "openai":

        def ask_openai(system: str, user: str) -> str:
            return openai_api.generate(system, user, model=model, json_mode=json_mode, usage=usage)

        return ask_openai
    if provider == "gemini":

        def ask_gemini(system: str, user: str) -> str:
            if usage is not None:
                usage.calls += 1
            return gemini.generate(system, user, model=model, json_mode=json_mode)

        return ask_gemini
    raise ValueError(f"unknown provider {provider!r}; choose one of {PROVIDERS}")
