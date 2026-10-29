"""Client-side rate limiter with two sliding windows (per second and per minute).

The clock and the sleep function are injected, so tests run instantly and deterministically.
When the wait would be longer than ``max_wait`` the limiter refuses with ``RateLimited``
instead of blocking a request worker.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

from ..errors import RateLimited

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class SlidingWindowLimiter:
    def __init__(
        self,
        *,
        per_second: int,
        per_minute: int,
        max_wait: float = 15.0,
        provider: str | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if per_second < 1 or per_minute < 1:
            raise ValueError("limits must be at least 1")
        self._windows = ((1.0, per_second), (60.0, per_minute))
        self._max_wait = max_wait
        self._provider = provider
        self._clock = clock
        self._sleep = sleep
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    def _wait_needed(self, now: float) -> float:
        wait = 0.0
        for span, limit in self._windows:
            recent = [t for t in self._hits if now - t < span]
            if len(recent) >= limit:
                # the call fits once the oldest hit in the window has aged out
                wait = max(wait, recent[-limit] + span - now)
        return wait

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                horizon = self._windows[-1][0]
                while self._hits and now - self._hits[0] >= horizon:
                    self._hits.popleft()
                wait = self._wait_needed(now)
                if wait <= 0:
                    self._hits.append(now)
                    return
                if wait > self._max_wait:
                    raise RateLimited(
                        "local rate limit reached",
                        provider=self._provider,
                        retry_after_seconds=wait,
                    )
                await self._sleep(wait)
