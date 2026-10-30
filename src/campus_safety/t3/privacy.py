"""Presidio screen for people's names before any training export (privacy spec B5)."""

from functools import cached_property
from typing import Any

THRESHOLD = 0.5


class PersonScreen:
    """True for text where Presidio finds a PERSON at or above THRESHOLD. Loaded on first use."""

    @cached_property
    def _engine(self) -> Any:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        ).create_engine()
        return AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])

    def has_person(self, text: str) -> bool:
        found = self._engine.analyze(text=text, language="en", entities=["PERSON"])
        return any(result.score >= THRESHOLD for result in found)
