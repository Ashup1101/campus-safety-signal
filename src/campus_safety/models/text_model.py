"""Checks on exported T2/T4 text-model weights before import: the exact keys, consistent lengths,
and no term that looks like record data (a long number such as a case or phone number, or an
email address). Training keeps only words seen in at least two items, so one-off names drop out."""

import re
from typing import Any

KEYS = {"vocabulary", "idf", "coef", "intercept", "threshold"}
_RECORD_LIKE = re.compile(r"\d{5,}|@")


def problems(weights: dict[str, Any]) -> list[str]:
    if set(weights) != KEYS:
        return ["unexpected keys"]
    vocabulary, idf, coef = weights["vocabulary"], weights["idf"], weights["coef"]
    if not (
        isinstance(vocabulary, dict)
        and len(idf) == len(coef) == len(vocabulary)
        and sorted(vocabulary.values()) == list(range(len(vocabulary)))
    ):
        return ["lengths differ"]
    if any(_RECORD_LIKE.search(str(term)) for term in vocabulary):
        return ["a term looks like a record (long number or email)"]
    return []
