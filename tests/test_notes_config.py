"""Community notes settings (configs/notes.yaml): defaults load and bad values are refused."""

from pathlib import Path

import pytest
import yaml

from campus_safety.notes import config


def test_defaults_match_the_owner_rules() -> None:
    found = config.load()
    assert found.threshold == 2 and found.event_night_threshold == 3
    assert found.text_limit == 140 and found.expiry_hours == 24 and found.report_threshold == 3
    assert found.nearby_m == 500
    assert set(found.safety_tags) <= set(found.tags)
    assert set(found.after_all_clear_tags) <= set(found.tags)
    assert not set(found.after_all_clear_tags) & set(found.safety_tags)
    assert "shooter" in found.alarming_words


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("threshold", 1, "threshold"),
        ("text_limit", 0, "text_limit"),
        ("safety_tags", ["Not a tag"], "safety_tags"),
    ],
)
def test_bad_values_are_refused(tmp_path: Path, key: str, value: object, message: str) -> None:
    raw = yaml.safe_load(config.CONFIG.read_text())
    raw[key] = value
    path = tmp_path / "notes.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=message):
        config.load(path)
