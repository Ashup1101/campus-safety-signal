"""RAG measurements (product.md B10): faithfulness and citation correctness, computed by rules
so they run in CI with a fake model and on the owner's question set with a real one.

- faithfulness: share of fact sentences (sentences with a citation) whose numbers and place
  words all appear in the lines they cite.
- citation correctness: share of citations that point at a retrieved line which shares at
  least one content word with the sentence citing it.
"""

import re
from dataclasses import dataclass

from campus_safety.rag.index import Hit

_CITE = re.compile(r"\[(\d{1,2})\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
_WORD = re.compile(r"[a-z0-9]{3,}")
STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "were",
        "was",
        "are",
        "has",
        "have",
        "had",
        "near",
        "about",
        "there",
        "their",
        "outcome",
        "data",
        "hold",
        "incident",
        "incidents",
        "reported",
    ]
)


@dataclass(frozen=True)
class Scores:
    sentences: int
    cited_sentences: int
    faithful_sentences: int
    citations: int
    correct_citations: int

    @property
    def faithfulness(self) -> float:
        return self.faithful_sentences / self.cited_sentences if self.cited_sentences else 0.0

    @property
    def citation_correctness(self) -> float:
        return self.correct_citations / self.citations if self.citations else 0.0


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS}


def score(answer: str, hits: list[Hit]) -> Scores:
    sentences = [s for s in _SENTENCE.split(answer) if s.strip()]
    cited = faithful = citations = correct = 0
    for sentence in sentences:
        refs = [int(n) for n in _CITE.findall(sentence)]
        if not refs:
            continue
        cited += 1
        body = _CITE.sub("", sentence)
        lines = [hits[n - 1].doc.text for n in refs if 1 <= n <= len(hits)]
        support = _words(" ".join(lines))
        claims = _words(body)
        numbers = set(re.findall(r"\b\d{1,4}\b", body))
        supported_numbers = set(re.findall(r"\b\d{1,4}\b", " ".join(lines)))
        if lines and numbers <= supported_numbers and (not claims or claims & support):
            faithful += 1
        for n in refs:
            citations += 1
            if 1 <= n <= len(hits) and claims & _words(hits[n - 1].doc.text):
                correct += 1
    return Scores(len(sentences), cited, faithful, citations, correct)
