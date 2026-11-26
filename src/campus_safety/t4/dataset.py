"""T4 dataset: attack texts from the red-team corpus (positives) and harmless made-up texts
(configs/redteam/benign.yaml, negatives). Test attack families (MITRE ATLAS techniques) are never
seen in training, so the score says how well the screen generalizes to new tricks."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campus_safety.security import redteam

BENIGN = Path(__file__).resolve().parents[3] / "configs" / "redteam" / "benign.yaml"
TEST_EVERY = 3  # every third family (sorted) and every third harmless text go to test


@dataclass(frozen=True)
class Row:
    text: str
    label: bool  # True: an attack
    family: str  # ATLAS technique for attacks, "benign" otherwise


@dataclass
class Dataset:
    train: list[Row] = field(default_factory=list)
    test: list[Row] = field(default_factory=list)


def build(corpus: Path = redteam.CORPUS, benign: Path = BENIGN) -> Dataset:
    attacks = [Row(c.text, True, c.atlas) for c in redteam.load(corpus) if c.text.strip()]
    harmless = [str(t) for t in (yaml.safe_load(benign.read_text()) or {}).get("texts", [])]
    families = sorted({r.family for r in attacks})
    held_out = set(families[TEST_EVERY - 1 :: TEST_EVERY]) or {families[-1]}
    data = Dataset()
    for row in attacks:
        (data.test if row.family in held_out else data.train).append(row)
    for i, text in enumerate(harmless):
        row = Row(text, False, "benign")
        (data.test if i % TEST_EVERY == TEST_EVERY - 1 else data.train).append(row)
    return data
