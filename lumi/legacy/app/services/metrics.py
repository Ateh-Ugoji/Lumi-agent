from app.models.post import MetricSnapshot

X_CHAR_LIMIT = 280


def _likes_per_hour(older: MetricSnapshot, newer: MetricSnapshot) -> float:
    hours = (newer.captured_at - older.captured_at).total_seconds() / 3600
    if hours <= 0:
        return 0.0
    return (newer.likes - older.likes) / hours


def current_and_baseline_velocity(snapshots: list[MetricSnapshot]) -> tuple[float, float]:
    """Likes/hour growth rate for a post, plus a baseline from the window before it.

    `current` is the growth rate between the two most recent snapshots. `baseline` is the growth rate
    from the pair before that (the rate just prior to the current window), or 0.0 if there isn't enough
    history yet.
    """
    if len(snapshots) < 2:
        return 0.0, 0.0

    ordered = sorted(snapshots, key=lambda s: s.captured_at)
    current = _likes_per_hour(ordered[-2], ordered[-1])
    baseline = _likes_per_hour(ordered[-3], ordered[-2]) if len(ordered) >= 3 else 0.0
    return current, baseline


SPIKE_FLOOR_LIKES_PER_HOUR = 5.0
SPIKE_MULTIPLIER = 3.0


def detect_spike(snapshots: list[MetricSnapshot]) -> bool:
    """A post is spiking if its current velocity is both above a minimum floor
    and significantly higher than its own baseline."""
    current, baseline = current_and_baseline_velocity(snapshots)
    if current < SPIKE_FLOOR_LIKES_PER_HOUR:
        return False
    if baseline <= 0:
        return current >= SPIKE_FLOOR_LIKES_PER_HOUR
    return current >= baseline * SPIKE_MULTIPLIER
