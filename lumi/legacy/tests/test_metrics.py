from datetime import UTC, datetime, timedelta

from app.models.post import MetricSnapshot
from app.services.metrics import current_and_baseline_velocity, detect_spike

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _snapshot(hours_after_t0: float, likes: int) -> MetricSnapshot:
    return MetricSnapshot(post_id=1, captured_at=T0 + timedelta(hours=hours_after_t0), likes=likes)


def test_velocity_needs_at_least_two_snapshots():
    assert current_and_baseline_velocity([]) == (0.0, 0.0)
    assert current_and_baseline_velocity([_snapshot(0, 10)]) == (0.0, 0.0)


def test_velocity_with_two_snapshots_has_no_baseline():
    snapshots = [_snapshot(0, 10), _snapshot(1, 30)]
    current, baseline = current_and_baseline_velocity(snapshots)
    assert current == 20.0  # 20 likes gained over 1 hour
    assert baseline == 0.0


def test_velocity_with_three_snapshots_computes_both():
    snapshots = [_snapshot(0, 10), _snapshot(1, 30), _snapshot(2, 90)]
    current, baseline = current_and_baseline_velocity(snapshots)
    assert current == 60.0  # between the two most recent: (90-30)/1h
    assert baseline == 20.0  # between the pair before that: (30-10)/1h


def test_detect_spike_relative_to_baseline():
    # current=60, baseline=20 → 3x jump → spike
    snapshots = [_snapshot(0, 10), _snapshot(1, 30), _snapshot(2, 90)]
    assert detect_spike(snapshots) is True


def test_detect_spike_no_spike_when_growth_is_steady():
    # current=20, baseline=20 → 1x, not 3x → no spike
    snapshots = [_snapshot(0, 10), _snapshot(1, 30), _snapshot(2, 50)]
    assert detect_spike(snapshots) is False


def test_detect_spike_below_floor():
    # current=1, well below the 5 likes/hr floor — never a spike
    snapshots = [_snapshot(0, 10), _snapshot(1, 1000), _snapshot(2, 1001)]
    current, baseline = current_and_baseline_velocity(snapshots)
    assert baseline == 990.0
    assert current == 1.0
    assert detect_spike(snapshots) is False


def test_detect_spike_no_baseline_uses_floor():
    # Only 2 snapshots → baseline=0, current=10 → above floor → spike
    snapshots = [_snapshot(0, 0), _snapshot(1, 10)]
    assert detect_spike(snapshots) is True
