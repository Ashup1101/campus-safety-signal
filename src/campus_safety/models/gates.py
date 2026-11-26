"""Gates from imported text models (T2 relevance, T4 injection screen): a yes/no function from the
newest run's JSON weights, or None when no run exists or the newest one lost to the rules. Weights
are hash-checked and shape-checked on load; scoring is plain Python."""

import json
from collections.abc import Callable

from campus_safety.lake.storage import Lake
from campus_safety.models import registry, text_model
from campus_safety.t2 import model

Gate = Callable[[str], bool]


def text_gate(lake: Lake, name: str) -> Gate | None:
    run = registry.latest(lake, name)
    if run is None or not registry.uses_model(run):
        return None
    weights = json.loads(registry.read(lake, run, "model.json"))
    if text_model.problems(weights):
        return None
    return lambda text: model.flags(weights, text)
