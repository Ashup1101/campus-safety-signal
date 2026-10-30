"""Presidio screen for people's names before any training export (privacy spec B5).

The small spaCy model reads the log's all-caps text poorly: it calls dates, times, streets, and
buildings named after people ("WRIGHT QUAD") PERSON. A detected span is therefore ignored when
every word in it is one the incident itself publishes as a structured field (location, offense,
disposition, case number), a form label, or when it has no letters at all (dates, times). What is
left is treated as a possible name and the pair is dropped.
"""

import re
from collections.abc import Iterable
from functools import cached_property
from typing import Any

THRESHOLD = 0.5
_WORD = re.compile(r"[A-Za-z]+")
LABEL_WORDS = frozenset(
    [
        "DATE",
        "REPORTED",
        "REPORT",
        "LOCATION",
        "GENERAL",
        "EVENT",
        "CAD",
        "INCIDENT",
        "INCIDENTS",
        "OFFENSES",
        "FINAL",
        "DISPOSITION",
        "OCCURRED",
        "FROM",
        "TO",
        "TIME",
        "AND",
        "AT",
        "ON",
        "OFF",
        "NON",
        "CAMPUS",
        "PUBLIC",
        "PROPERTY",
        "MODIFIED",
        "CASE",
        "NUMBER",
        "CRIME",
        "DESCRIPTION",
        "X",
        "MON",
        "TUE",
        "WED",
        "THU",
        "FRI",
        "SAT",
        "SUN",
        "TR",
        "TD",
        "STRONG",
        "ROLE",
        "ROW",
        "CLASS",
        "COLUMNHEADER",
        "PRESENTATION",
    ]
)


def known_words(values: Iterable[object]) -> frozenset[str]:
    return frozenset(w.upper() for value in values if value for w in _WORD.findall(str(value)))


def is_known(span: str, known: frozenset[str]) -> bool:
    return all(word.upper() in known or word.upper() in LABEL_WORDS for word in _WORD.findall(span))


class PersonScreen:
    """Possible people's names in text, from Presidio, minus spans the incident itself explains."""

    @cached_property
    def _engine(self) -> Any:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                "ner_model_configuration": {"labels_to_ignore": ["CARDINAL", "ORDINAL"]},
            }
        ).create_engine()
        return AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])

    def names(self, text: str, known: frozenset[str] = frozenset()) -> list[str]:
        found = self._engine.analyze(text=text, language="en", entities=["PERSON"])
        spans = (text[r.start : r.end] for r in found if r.score >= THRESHOLD)
        return [span for span in spans if not is_known(span, known)]

    def has_person(self, text: str, known: frozenset[str] = frozenset()) -> bool:
        return bool(self.names(text, known))
