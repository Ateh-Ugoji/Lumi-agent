"""LinkedIn social adapter for public competitor analysis and connected feed ingestion."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from lumi_ai.ports import Platform, PostIn, PostMetrics, UserInfo

log = logging.getLogger(__name__)


class LinkedInSocialData:
    """Reads LinkedIn member and creator posts for competitor analysis."""

    async def fetch_user_posts(
        self, handle: str, since: datetime | None, limit: int
    ) -> list[PostIn]:
        from apps.connections.accounts import get_config
        from apps.connections.models import ConnectedAccount
        from apps.connections.providers.registry import build_provider
        from apps.intelligence.repos.aio import aio
        from apps.profiles.models import Post

        clean = handle.strip().lstrip("@").lower()

        # 1. Connected account OAuth check (if member connected)
        try:
            acc = await aio(
                lambda: ConnectedAccount.objects.filter(
                    platform="linkedin", status="active"
                ).first()
            )()
            if acc and acc.tokens and getattr(acc.tokens, "access_token", None):
                from apps.connections.providers.registry import build_provider

                config = get_config()
                provider = build_provider("linkedin", config)
                account_info = await provider.get_account(acc.tokens)
                posts = await provider.fetch_posts(acc.tokens, account_info, limit=limit)
                if posts:
                    if since:
                        since_aware = (
                            since.replace(tzinfo=UTC)
                            if since.tzinfo is None
                            else since
                        )
                        posts = [
                            p
                            for p in posts
                            if p.published_at and p.published_at >= since_aware
                        ]
                    return posts[:limit]
        except Exception as exc:  # noqa: BLE001
            log.debug("LinkedIn connected fetch skipped/failed: %s", exc)

        # 2. Database store check for existing posts from this author
        try:
            db_posts = await aio(
                lambda: list(
                    Post.objects.filter(
                        author__platform="linkedin",
                        author__handle_normalized__iexact=clean,
                    ).order_by("-published_at")[:limit]
                )
            )()
            if db_posts:
                return [
                    PostIn(
                        platform="linkedin",
                        external_id=str(p.external_id or p.pk),
                        author_handle=clean,
                        text=p.text or getattr(p, "caption", "") or "",
                        published_at=p.published_at or datetime.now(UTC),
                        metrics=PostMetrics(
                            likes=p.metrics.get("likes", 0)
                            if isinstance(p.metrics, dict)
                            else 0
                        ),
                        url=p.url
                        or f"https://www.linkedin.com/feed/update/{p.external_id}/",
                        source="linkedin",
                    )
                    for p in db_posts
                ]
        except Exception as exc:  # noqa: BLE001
            log.debug("LinkedIn db fetch skipped: %s", exc)

        return []

    async def search_posts(self, query: str, limit: int) -> list[PostIn]:
        from apps.intelligence.repos.aio import aio
        from apps.profiles.models import Post

        try:
            db_posts = await aio(
                lambda: list(
                    Post.objects.filter(
                        author__platform="linkedin",
                        text__icontains=query,
                    ).order_by("-published_at")[:limit]
                )
            )()
            return [
                PostIn(
                    platform="linkedin",
                    external_id=str(p.external_id or p.pk),
                    author_handle=p.author.handle_normalized or "creator",
                    text=p.text or getattr(p, "caption", "") or "",
                    published_at=p.published_at or datetime.now(UTC),
                    metrics=PostMetrics(
                        likes=p.metrics.get("likes", 0)
                        if isinstance(p.metrics, dict)
                        else 0
                    ),
                    url=p.url
                    or f"https://www.linkedin.com/feed/update/{p.external_id}/",
                    source="linkedin",
                )
                for p in db_posts
            ]
        except Exception:  # noqa: BLE001
            return []

    async def get_user(self, handle: str) -> UserInfo | None:
        clean = handle.strip().lstrip("@")
        return UserInfo(platform="linkedin", handle=clean, display_name=clean)

    async def search_users(self, query: str, limit: int) -> list[UserInfo]:
        clean = query.strip().lstrip("@")
        return [UserInfo(platform="linkedin", handle=clean, display_name=clean)]
