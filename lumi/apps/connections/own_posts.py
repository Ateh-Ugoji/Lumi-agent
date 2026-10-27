"""Pure paging of a connected account feed into ``PostIn`` objects.

This is the provider half of the ``OwnPostSync`` port. Storing the posts is done by
``apps.profiles.services`` once it exists, so this module only reads and maps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from lumi_ai.ports import PostIn

from .clients.pfm import PfmClient
from .ingest import map_pfm_item, parse_datetime

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 10


@dataclass(frozen=True, slots=True)
class OwnPostsResult:
    posts: tuple[PostIn, ...]
    skipped: int  # items that could not be mapped (no id, text or date)
    pages: int
    stopped: str  # "limit" | "since" | "end" | "max_pages"


async def collect_own_posts(
    client: PfmClient,
    account_id: str,
    *,
    handle: str | None,
    limit: int,
    since: datetime | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> OwnPostsResult:
    """Read the feed newest first until ``limit`` posts, the ``since`` date or the end."""
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    posts: list[PostIn] = []
    skipped = 0
    pages = 0
    cursor: str | None = None
    stopped = "end"
    while True:
        if pages >= max_pages:
            stopped = "max_pages"
            break
        page = await client.get_account_feed_page(
            account_id, limit=min(DEFAULT_PAGE_SIZE, max(limit, 1)), cursor=cursor
        )
        pages += 1
        reached_old = False
        for item in page.items:
            published = parse_datetime(item.get("posted_at"))
            if since is not None and published is not None and published < since:
                reached_old = True
                continue
            mapped = map_pfm_item(item, handle=handle)
            if mapped is None:
                skipped += 1
                continue
            posts.append(mapped)
            if len(posts) >= limit:
                return OwnPostsResult(tuple(posts), skipped, pages, "limit")
        if reached_old:
            stopped = "since"
            break
        if not page.has_more:
            break
        cursor = page.cursor
    return OwnPostsResult(tuple(posts), skipped, pages, stopped)
