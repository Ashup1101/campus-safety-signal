"""The console's "Tonight model" card: the newest imported T1 scorecard (method in use, test
scores against both baselines, when it was trained). Numbers only."""

import json
from typing import Any

from campus_safety.lake.storage import LakeConfigError, open_lake

FIELDS = ("method", "model", "scores", "event_multiplier", "split_rows", "trained_at", "run_id")


def card(lake_uri: str) -> dict[str, Any]:
    try:
        lake = open_lake(lake_uri)
        stamps = [
            (json.loads(lake.get(key))["imported_at"], key.removesuffix("import.json"))
            for key in lake.keys("t1/")
            if key.endswith("/import.json")
        ]
    except (LakeConfigError, OSError):
        return {"method": None}
    if not stamps:
        return {"method": None}
    _, prefix = max(stamps)
    scorecard = json.loads(lake.get(prefix + "scorecard.json"))
    return {name: scorecard[name] for name in FIELDS}
