"""A write that must not commit after its tool call gave up.

The agent loop runs a tool under a timeout. Cancelling the coroutine cannot stop a database
write already running in a worker thread, so without help the row would be saved *after* the
model was told the tool failed. A :class:`CancelToken` closes that gap:

* the loop opens a token for every tool that writes and publishes it through :data:`current`;
* the Django glue (``apps.intelligence.repos.aio``) runs each blocking write inside a
  transaction and, just before the commit, calls :meth:`CancelToken.commit_gate`, which raises
  :class:`WriteCancelled` when the token was cancelled, so the transaction rolls back;
* the loop calls :meth:`CancelToken.cancel` when the timeout fires. It first sets the flag, then
  waits for a commit that is already in flight, and returns how many commits went through.

Why this is airtight: the committer takes the lock *then* reads the flag; the canceller sets the
flag *then* takes the lock. Either the committer sees the flag and rolls back, or it already holds
the lock and the canceller waits for the commit to finish and reports it.

Limits (by design): a tool that makes several separate writes keeps the ones committed before the
timeout (``commits`` says so); writes to external systems (Meta, MCP connectors) and vector
upserts cannot be rolled back.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar


class WriteCancelled(Exception):
    """Raised inside a write transaction whose tool call already timed out."""


class CancelToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._commits = 0

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def commits(self) -> int:
        return self._commits

    def cancel_nowait(self) -> None:
        """Forbid any commit that has not started. Never blocks (safe on the event loop)."""
        self._cancelled = True

    def cancel(self) -> int:
        """Forbid new commits, wait for one in flight, return how many commits happened.

        Blocks for at most one commit: call it from a thread, not from the event loop.
        """
        self._cancelled = True
        with self._lock:
            return self._commits

    def commit_gate(self) -> _Gate:
        """Call inside the open transaction, right before it commits.

        ``with token.commit_gate():`` raises :class:`WriteCancelled` if the token is cancelled;
        otherwise it holds the lock until the ``with`` block ends, which the caller arranges to
        be *after* the commit.
        """
        return _Gate(self)


class _Gate:
    def __init__(self, token: CancelToken) -> None:
        self._token = token

    def __enter__(self) -> None:
        self._token._lock.acquire()
        if self._token._cancelled:
            self._token._lock.release()
            raise WriteCancelled("the tool call timed out; the write was rolled back")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self._token._commits += 1
        self._token._lock.release()


#: The token of the tool call running in this context (None: no cancellation guard).
current: ContextVar[CancelToken | None] = ContextVar("lumi_cancel_token", default=None)
