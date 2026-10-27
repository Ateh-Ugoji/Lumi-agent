"""Pure paging of a connected account feed into ``PostIn`` objects.

This is the provider half of the ``OwnPostSync`` port. Storing the posts is done by
``apps.profiles.services`` once it exists, so this module only reads and maps.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from lumi_ai.ports import PostIn

from .clients.pfm import PfmClient
from .errors import ProviderAuthError, SocialDataError
from .ingest import map_pfm_item, parse_datetime
from .providers.base import AccountInfo, SocialProvider, TokenSet

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 10


@dataclass(frozen=True, slots=True)
class OwnPostsResult:
    posts: tuple[PostIn, ...]
    skipped: int  # items that could not be mapped (no id, text or date)
    pages: int
    stopped: str  # "limit" | "since" | "end" | "max_pages"
    # Only the native providers read metrics one post at a time; Post for Me sends them in the feed.
    metrics_read: int = 0
    metrics_failed: int = 0


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


async def collect_meta_posts(
    provider: SocialProvider,
    tokens: TokenSet,
    account: AccountInfo,
    *,
    handle: str | None,
    limit: int,
    metrics_limit: int,
) -> OwnPostsResult:
    """Read a Facebook Page's newest posts, then the metrics of the newest ``metrics_limit``.

    Graph answers metrics one post per request, so they are bounded: a Page with a long history
    would otherwise spend a request per post on every sync. A post whose metrics fail keeps its row
    and every counter stays ``None`` (never ``0``); a rejected token stops the metric reads, since
    the rest would fail the same way. The post list itself is not guarded: if it fails the sync
    fails, and the caller decides what that means.
    """
    posts = await provider.fetch_posts(tokens, account, limit=limit)
    enriched: list[PostIn] = []
    read = failed = 0
    budget = metrics_limit
    for post in posts:
        post = replace(post, author_handle=handle)
        if budget > 0:
            budget -= 1
            try:
                post = replace(
                    post,
                    metrics=await provider.fetch_metrics(
                        tokens, account, post.external_id
                    ),
                )
                read += 1
            except ProviderAuthError:
                failed += 1
                budget = 0
            except SocialDataError:
                failed += 1
        enriched.append(post)
    return OwnPostsResult(
        posts=tuple(enriched),
        skipped=0,
        pages=1,
        stopped="limit" if len(posts) >= min(limit, 100) else "end",
        metrics_read=read,
        metrics_failed=failed,
    )
