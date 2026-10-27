"""End of an ingest pass: which stored posts the source stopped returning.

Port of ``is_second_miss``, ``pass_reached_window`` and ``finalize_ingest_pass`` from
``app/services/ingest.py``. A pass is one newest-first read of an account's posts. After it:

* every post the pass returned gets ``last_seen_at = pass start``;
* a post that is inside the last 30 days and missed TWO consecutive complete passes is flagged
  ``is_deleted_suspect`` (analytics leave it out); a pass that did not reach the post's date, or
  did not finish, never counts as a miss;
* one ``IngestPass`` row is written per pass, so the next pass knows when the previous one ran.

Two differences from the legacy code, both on the side of not hiding a real post:

* the previous pass is the last COMPLETE one (the legacy used any snapshot, so an interrupted
  pass could count as the first miss);
* a flagged post that a later pass returns is cleared (the legacy never cleared it, so one bad
  response hid a post for good).

Pure Python over ``PassStore``. The Django one is ``stores.DjangoPassStore``.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

DELETION_WINDOW = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class StoredPost:
    key: int
    external_id: str
    published_at: datetime | None
    last_seen_at: datetime | None
    suspect: bool


@dataclass(frozen=True, slots=True)
class PassResult:
    seen: int
    flagged_deleted: int
    cleared: int
    complete: bool


class PassStore(Protocol):
    async def last_complete_pass(
        self, handle_id: int, before: datetime
    ) -> datetime | None: ...

    async def posts(self, handle_id: int) -> list[StoredPost]: ...

    async def save_pass(
        self,
        handle_id: int,
        *,
        started_at: datetime,
        source: str,
        complete: bool,
        seen: list[int],
        flag: list[int],
        clear: list[int],
    ) -> None:
        """Atomic: the pass row, ``last_seen_at`` of ``seen``, and the suspect marks."""
        ...


def is_second_miss(
    last_seen_at: datetime | None,
    prev_pass_at: datetime | None,
    published_at: datetime | None,
    *,
    now: datetime,
    pass_complete: bool,
    oldest_fetched: datetime | None = None,
    newest_fetched: datetime | None = None,
) -> bool:
    """True when a post inside the 30 day window missed two consecutive complete passes.

    Bracket guard: the pass must have fetched posts both older and newer than this one, or
    "missing" only means "outside the slice that was read".
    """
    if not pass_complete or prev_pass_at is None:
        return False  # incomplete pass, or the first one ever: no evidence
    if last_seen_at is None or published_at is None:
        return False  # never seen, or undated: cannot prove two misses
    if now - published_at > DELETION_WINDOW:
        return False  # only the last 30 days are tracked
    if oldest_fetched is None or newest_fetched is None:
        return False
    if not (oldest_fetched < published_at < newest_fetched):
        return False  # the slice does not span this post's date
    return last_seen_at < prev_pass_at


def pass_reached_window(
    oldest_published: datetime | None, *, now: datetime | None = None
) -> bool:
    """A newest-first read covered the deletion window when its oldest item is older than 30 days."""
    now = now or datetime.now(UTC)
    return oldest_published is not None and oldest_published < now - DELETION_WINDOW


async def finalize_pass(
    store: PassStore,
    handle_id: int,
    *,
    fetched_ids: Collection[str],
    source: str,
    pass_started: datetime,
    pass_complete: bool,
    fetched_window: tuple[datetime, datetime] | None = None,
) -> PassResult:
    """Bookkeeping for one pass. ``fetched_window`` is (oldest, newest) published date read."""
    prev = await store.last_complete_pass(handle_id, pass_started)
    oldest, newest = fetched_window if fetched_window else (None, None)
    fetched = set(fetched_ids)
    seen: list[int] = []
    flag: list[int] = []
    clear: list[int] = []
    for post in await store.posts(handle_id):
        if post.external_id in fetched:
            seen.append(post.key)
            if post.suspect:
                clear.append(post.key)
        elif not post.suspect and is_second_miss(
            post.last_seen_at,
            prev,
            post.published_at,
            now=pass_started,
            pass_complete=pass_complete,
            oldest_fetched=oldest,
            newest_fetched=newest,
        ):
            flag.append(post.key)
    await store.save_pass(
        handle_id,
        started_at=pass_started,
        source=source,
        complete=pass_complete,
        seen=seen,
        flag=flag,
        clear=clear,
    )
    return PassResult(len(seen), len(flag), len(clear), pass_complete)
