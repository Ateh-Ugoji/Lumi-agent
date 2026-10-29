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
from django.db import transaction

from lumi_ai import cancel


def _guarded[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Run ``fn`` so it cannot commit after the tool call that started it timed out.

    Without a token in the context (reads, endpoints, tasks) ``fn`` runs untouched. With one, ``fn``
    runs in a transaction and the commit is gated: see ``lumi_ai.cancel``.
    """

    @functools.wraps(fn)
    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        token = cancel.current.get()
        if token is None:
            return fn(*args, **kwargs)
        if token.cancelled:
            raise cancel.WriteCancelled(
                "the tool call timed out before the write began"
            )
        gate = token.commit_gate()
        gated = False
        try:
            with transaction.atomic():
                result = fn(*args, **kwargs)
                gate.__enter__()  # raises WriteCancelled: the transaction rolls back
                gated = True
            # the transaction committed here, with the gate still held
        except BaseException as exc:
            if gated:
                gate.__exit__(type(exc), exc, exc.__traceback__)
            raise
        gate.__exit__(None, None, None)
        return result

    return run


def aio[**P, R](fn: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    runner = sync_to_async(_guarded(fn), thread_sensitive=True)

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> R:
        return await runner(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
