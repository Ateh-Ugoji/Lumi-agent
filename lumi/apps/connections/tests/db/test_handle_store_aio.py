"""``DjangoHandleStore`` writes obey the tool call's ``CancelToken``.

``scan_trends`` and ``search_frameworks`` write handles through ``HandleDirectory`` inside a tool
call. When that call has timed out, none of them may commit afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from asgiref.sync import async_to_sync

from apps.connections.handles.directory import HandleDirectory
from apps.connections.handles.types import CacheEntry, HandleRow
from apps.connections.models import HandleSearchCache
from apps.connections.stores import DjangoHandleStore
from apps.profiles.models import SocialHandle
from lumi_ai import cancel

pytestmark = pytest.mark.django_db

ROW = HandleRow("karpathy", "x", "Andrej", "https://img/k.jpg", 7, "live")


@pytest.fixture
def timed_out():
    """A tool call that already timed out: its token is cancelled and is the current one."""
    token = cancel.CancelToken()
    token.cancel_nowait()
    reset = cancel.current.set(token)
    yield token
    cancel.current.reset(reset)


def written() -> tuple[int, int]:
    return SocialHandle.objects.count(), HandleSearchCache.objects.count()


WRITERS = {
    "remember_live": lambda s: s.remember_live([ROW]),
    "remember_new": lambda s: s.remember_new([ROW]),
    "remember_rows": lambda s: s.remember_rows([ROW], "niche"),
    "put_entry": lambda s: s.put_entry(
        CacheEntry("x", "kar", datetime(2026, 10, 27, tzinfo=UTC), (ROW,))
    ),
}


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_a_writer_commits_nothing_after_the_tool_call_timed_out(
    timed_out, name
) -> None:
    with pytest.raises(cancel.WriteCancelled):
        async_to_sync(lambda: WRITERS[name](DjangoHandleStore()))()
    assert written() == (0, 0)


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_the_same_writer_works_without_a_tool_call(name) -> None:
    async_to_sync(lambda: WRITERS[name](DjangoHandleStore()))()
    assert written() != (0, 0)


def test_a_scan_saving_handles_after_a_timeout_saves_none(timed_out) -> None:
    """The directory swallows its own failures, so the guard has to hold at the store."""
    async_to_sync(HandleDirectory(DjangoHandleStore()).remember_scanned)(
        ["karpathy", "sama"], origin="niche"
    )
    assert SocialHandle.objects.count() == 0
