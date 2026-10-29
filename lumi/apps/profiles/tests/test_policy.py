"""Pure rules ported from the legacy metrics and ingest code. No database."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from apps.profiles import policy

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class Reading:
    captured_at: datetime
    likes: int | None = None
    views: int | None = None


def reading(hours: float, likes: int) -> Reading:
    return Reading(T0 + timedelta(hours=hours), likes)


def test_velocity_needs_at_least_two_readings():
    assert policy.current_and_baseline_velocity([]) == (0.0, 0.0)
    assert policy.current_and_baseline_velocity([reading(0, 10)]) == (0.0, 0.0)


def test_velocity_with_two_readings_has_no_baseline():
    current, baseline = policy.current_and_baseline_velocity(
        [reading(0, 10), reading(1, 30)]
    )
    assert (current, baseline) == (20.0, 0.0)


def test_velocity_with_three_readings_computes_both_and_ignores_input_order():
    readings = [reading(2, 90), reading(0, 10), reading(1, 30)]
    assert policy.current_and_baseline_velocity(readings) == (60.0, 20.0)


def test_spike_is_three_times_the_baseline():
    assert policy.detect_spike([reading(0, 10), reading(1, 30), reading(2, 90)])
    assert not policy.detect_spike([reading(0, 10), reading(1, 30), reading(2, 50)])


def test_no_spike_below_the_floor_even_after_a_huge_baseline():
    readings = [reading(0, 10), reading(1, 1000), reading(2, 1001)]
    assert policy.current_and_baseline_velocity(readings) == (1.0, 990.0)
    assert not policy.detect_spike(readings)


def test_spike_without_a_baseline_only_needs_the_floor():
    assert policy.detect_spike([reading(0, 0), reading(1, 10)])
    assert not policy.detect_spike([reading(0, 0), reading(1, 4)])


def test_a_missing_like_count_counts_as_zero_and_two_readings_at_one_instant_give_zero():
    assert policy.current_and_baseline_velocity(
        [Reading(T0), Reading(T0 + timedelta(hours=1), 8)]
    ) == (8.0, 0.0)
    assert policy.current_and_baseline_velocity([reading(1, 5), reading(1, 50)]) == (
        0.0,
        0.0,
    )


def test_final_metrics_picks_the_reading_nearest_72_hours():
    readings = [
        Reading(T0 + timedelta(hours=h), views=v)
        for h, v in ((24, 10), (70, 30), (168, 40))
    ]
    assert policy.final_metrics(T0, readings) is readings[1]
    assert policy.final_metrics(T0, []) is None
    assert policy.final_metrics(None, readings) is None


def test_infer_timezone_needs_ten_posts():
    evening = T0.replace(hour=20)
    assert policy.infer_timezone([]) is None
    assert policy.infer_timezone([evening] * 9) is None
    assert policy.infer_timezone([evening] * 10) == "UTC+01:00"


def test_infer_timezone_breaks_a_tie_toward_the_lowest_hour():
    posts = [T0.replace(hour=20)] * 5 + [T0.replace(hour=6)] * 5
    assert policy.infer_timezone(posts) == "UTC-09:00"  # hour 6 wins the tie


def test_timezone_update_sets_the_inference_once():
    posts = [T0.replace(hour=20)] * 12
    assert policy.timezone_update(None, None, posts) == "UTC+01:00"
    assert policy.timezone_update("UTC+01:00", "inferred", posts) is None
    assert policy.timezone_update("UTC+05:00", "inferred", posts) == "UTC+01:00"


def test_a_confirmed_timezone_is_never_replaced():
    posts = [T0.replace(hour=6)] * 12
    assert policy.timezone_update("Africa/Lagos", "user_confirmed", posts) is None
