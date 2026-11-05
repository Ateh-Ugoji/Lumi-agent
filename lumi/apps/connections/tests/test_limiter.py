from __future__ import annotations

import pytest

from apps.connections.clients.limiter import SlidingWindowLimiter
from apps.connections.errors import RateLimited


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make(time: FakeTime, **kw) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        per_second=kw.pop("per_second", 5),
        per_minute=kw.pop("per_minute", 40),
        clock=time.clock,
        sleep=time.sleep,
        **kw,
    )


async def test_calls_under_the_limit_do_not_wait() -> None:
    t = FakeTime()
    limiter = make(t)
    for _ in range(5):
        await limiter.acquire()
    assert t.slept == []


async def test_sixth_call_in_one_second_waits_until_the_window_clears() -> None:
    t = FakeTime()
    limiter = make(t)
    for _ in range(6):
        await limiter.acquire()
    assert len(t.slept) == 1 and t.slept[0] == pytest.approx(1.0)


async def test_minute_window_blocks_the_41st_call() -> None:
    t = FakeTime()
    limiter = make(t, per_second=100, max_wait=120)
    for _ in range(40):
        await limiter.acquire()
    await limiter.acquire()
    assert sum(t.slept) == pytest.approx(60.0)


async def test_wait_longer_than_max_wait_is_refused_not_slept() -> None:
    t = FakeTime()
    limiter = make(t, per_second=100, max_wait=5, provider="pfm")
    for _ in range(40):
        await limiter.acquire()
    with pytest.raises(RateLimited) as caught:
        await limiter.acquire()
    assert caught.value.retry_after_seconds == pytest.approx(60.0)
    assert t.slept == []


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError):
        SlidingWindowLimiter(per_second=0, per_minute=1)
