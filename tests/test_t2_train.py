"""T2 fit on made-up items. Runs in CI (train group); skipped on the laptop (no local training)."""

import pytest

pytest.importorskip("sklearn")

from datetime import datetime, timedelta

from campus_safety.t2 import dataset, model, train


def test_fit_export_and_switch(tmp_path: object) -> None:
    t0 = datetime(2026, 9, 1)
    items = [
        {
            "item_id": f"i{n}",
            "title": "Robbery near Kirkwood" if n % 2 else "Concert review downtown",
            "summary": "",
            "published_at": t0 + timedelta(days=n),
            "relevant": bool(n % 2),
        }
        for n in range(40)
    ]
    truth = {f"i{n}": bool(n % 2) for n in range(28, 40)}
    data = dataset.build(items, truth, test_share=0.3)
    weights = train.fit(data.train)
    assert model.flags({**weights, "threshold": 0.5}, "Robbery near Kirkwood")
    rule = [r.label for r in data.test]
    card = train.scorecard(data, rule, "gh-1", weights)
    assert card["method"] in ("model", "rules") and card["provisional"] is False
