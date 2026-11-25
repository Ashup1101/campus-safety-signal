"""T1 seven-night forecast: expected calls, level and reason per zone and night. Made-up rows."""

from datetime import date, timedelta

from campus_safety.events import Event
from campus_safety.t1 import baselines, forecast
from campus_safety.t1.baselines import Row

START = date(2026, 10, 27)  # Tuesday; Halloween weekend is Fri Oct 30 + Sat Oct 31
EVENTS = [
    Event("halloween_2026", "Halloween weekend", (date(2026, 10, 30), date(2026, 10, 31)), "x")
]
NIGHTS = frozenset(EVENTS[0].nights)


def history(zone: str, calls: int) -> list[Row]:
    nights = [START - timedelta(days=d) for d in range(400, 0, -1)]
    return [Row(zone, n, calls, n.weekday(), n.month, False, calls, float(calls)) for n in nights]


def rule(multiplier: float) -> forecast.Predict:
    return lambda rows: [baselines.rule(r, multiplier) for r in rows]


def test_seven_nights_per_zone_with_event_nights_marked() -> None:
    rows = history("LB1", 1) + history("LB2", 0)
    found = forecast.forecast(rows, START, rule(3.0), "rule", EVENTS)
    assert len(found) == 2 * 7
    assert {f.night for f in found} == {START + timedelta(days=d) for d in range(7)}
    busy = {f.night: f for f in found if f.zonecode == "LB1"}
    assert busy[date(2026, 10, 27)].level == "quiet"
    assert busy[date(2026, 10, 27)].reason == "About a usual night here"
    assert busy[date(2026, 10, 31)].level == "high"
    assert busy[date(2026, 10, 31)].reason == "Expected much busier than usual: Halloween weekend"
    assert busy[date(2026, 10, 31)].expected == 3.0
    assert all(f.method == "rule" and f.window == "late_night" for f in found)


def test_a_quiet_zone_never_turns_high_over_a_fraction_of_a_call() -> None:
    found = forecast.forecast(history("LB2", 0), START, rule(3.0), "rule", EVENTS)
    assert {f.level for f in found} == {"quiet"}


def test_reasons_never_use_safe_or_risk_and_model_shape_matches() -> None:
    rows = history("LB1", 1)
    model = forecast.forecast(rows, START, lambda rs: [2.0 for _ in rs], "model", EVENTS)
    assert {f.level for f in model} == {"elevated"}  # 2x a usual night
    text = " ".join(f.reason.lower() for f in model)
    assert "safe" not in text and "risk" not in text
    assert {f.method for f in model} == {"model"}
    assert model[0].expected == 2.0
