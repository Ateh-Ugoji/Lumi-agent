"""Pure rules ported from the legacy ingest and metrics code. No ORM access and no clock.

Every function takes plain values (datetimes, numbers, objects with a ``captured_at`` and
``likes``) so a test can call it without a database. ``MetricSnapshot`` rows satisfy
``LikeReading`` and ``Reading``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

SPIKE_FLOOR_LIKES_PER_HOUR = 5.0
SPIKE_MULTIPLIER = 3.0
TARGET_SNAPSHOT_AGE_HOURS = 72.0
MIN_TIMEZONE_POSTS = 10
LOCAL_EVENING_HOUR = 21


class Reading(Protocol):
    captured_at: datetime


class LikeReading(Reading, Protocol):
    likes: int | None


def _likes_per_hour(older: LikeReading, newer: LikeReading) -> float:
    hours = (newer.captured_at - older.captured_at).total_seconds() / 3600
    if hours <= 0:
        return 0.0
    return ((newer.likes or 0) - (older.likes or 0)) / hours


def current_and_baseline_velocity(
    readings: Sequence[LikeReading],
) -> tuple[float, float]:
    """Likes per hour between the two newest readings, and between the pair before them.

    The baseline is ``0.0`` with fewer than three readings. Fewer than two give ``(0.0, 0.0)``.
    A missing ``likes`` counts as 0, as the legacy code did with its non-null column.
    """
    if len(readings) < 2:
        return 0.0, 0.0
    ordered = sorted(readings, key=lambda r: r.captured_at)
    current = _likes_per_hour(ordered[-2], ordered[-1])
    baseline = _likes_per_hour(ordered[-3], ordered[-2]) if len(ordered) >= 3 else 0.0
    return current, baseline


def detect_spike(readings: Sequence[LikeReading]) -> bool:
    """A spike is a current velocity above the floor and at least 3x the post's own baseline."""
    current, baseline = current_and_baseline_velocity(readings)
    if current < SPIKE_FLOOR_LIKES_PER_HOUR:
        return False
    if baseline <= 0:
        return True
    return current >= baseline * SPIKE_MULTIPLIER


def final_metrics[R: Reading](
    published_at: datetime | None, readings: Sequence[R]
) -> R | None:
    """The reading closest to 72 hours after publication: the post's "final" numbers.

    ``None`` with no readings or with no publication time to measure the age from.
    """
    if not readings or published_at is None:
        return None

    def distance(reading: R) -> float:
        age = (reading.captured_at - published_at).total_seconds() / 3600
        return abs(age - TARGET_SNAPSHOT_AGE_HOURS)

    return min(readings, key=distance)


def infer_timezone(published: Sequence[datetime]) -> str | None:
    """Weak guess: the most common UTC posting hour is taken to be 21:00 local.

    ``None`` below 10 posts. A tie goes to the lowest hour. The result is ``UTC+01:00`` shaped,
    from -12 to +11.
    """
    if len(published) < MIN_TIMEZONE_POSTS:
        return None
    counts = Counter(moment.hour for moment in published)
    mode = max(sorted(counts), key=lambda hour: counts[hour])
    offset = ((LOCAL_EVENING_HOUR - mode + 12) % 24) - 12
    return f"UTC{offset:+03d}:00"


def timezone_update(
    current: str | None, source: str | None, published: Sequence[datetime]
) -> str | None:
    """The inferred timezone to store, or ``None`` when nothing should change.

    A timezone the user confirmed is never replaced, and an inference equal to the stored
    inferred value is a no-op. The caller stores the result with source ``inferred``.
    """
    if source == "user_confirmed":
        return None
    inferred = infer_timezone(published)
    if inferred is None or (current == inferred and source == "inferred"):
        return None
    return inferred
