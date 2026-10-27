"""Run a blocking ORM function from async code.

The ports are async (the agent loop is) and the Django ORM used by ``apps.*.services`` is sync.
``@aio`` turns a plain method into the coroutine the port declares, running it on Django's
thread-sensitive executor, so each call gets a normal request-style connection that is closed
with the thread (no connection leaks) and a test transaction is seen by the code under test.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from asgiref.sync import sync_to_async


def aio[**P, R](fn: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    runner = sync_to_async(fn, thread_sensitive=True)

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> R:
        return await runner(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
