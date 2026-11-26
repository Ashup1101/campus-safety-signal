"""T4 injection screen: dataset split by attack family and the recall-at-low-false-positive rule.
Made-up text only."""

from campus_safety.t4 import dataset


def test_attack_families_in_test_are_never_seen_in_training() -> None:
    data = dataset.build()
    train_families = {r.family for r in data.train if r.label}
    test_families = {r.family for r in data.test if r.label}
    assert test_families and not train_families & test_families
    assert any(not r.label for r in data.test) and any(not r.label for r in data.train)
    assert all(r.text for r in data.train + data.test)
