"""Xpoz API client for social listening.

See .agents/external-services.md for architectural separation:
PFM handles the creator's own posts (voice extraction);
Xpoz handles third-party / market trends (repurposing candidates).
"""

import httpx

from app.config import get_settings

BASE_URL = "https://api.xpoz.ai"


class XpozClient:
    def __init__(self) -> None:
        settings = get_settings()
        headers = {}
        if settings.xpoz_api_key:
            headers["Authorization"] = f"Bearer {settings.xpoz_api_key}"

        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=headers,
            timeout=15.0,
        )

    # Verified against the API's own allowed-fields list (docs/profile_extract_audit.md
    # "Capabilities"): structural flags (replyTo*/conversationId/quotedTweetId/isRetweet)
    # + quote/bookmark counts + entities are all accepted. isReply/isQuote/mediaType do
    # NOT exist — derive them from replyToTweetId/quotedTweetId instead.
    USER_LIVE_FIELDS = (
        "id,text,authorUsername,createdAt,likeCount,retweetCount,replyCount,impressionCount,"
        "quoteCount,bookmarkCount,lang,isRetweet,conversationId,quotedTweetId,"
        "replyToTweetId,replyToUserId,replyToUsername,hashtags,mentions,urls,mediaUrls"
    )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_user_live_posts(
        self,
        username: str,
        limit: int = 15,
        fields: str = USER_LIVE_FIELDS,
    ) -> list[dict]:
        """Fetch a public X account's recent tweets on demand with engagement metrics.

        NOTE: the server ignores `limit` and always returns one 20-post page —
        pagination goes through get_user_live_posts_page + cursor.
        """
        results, _, _ = await self.get_user_live_posts_page(
            username.lstrip("@").strip(), limit=limit, fields=fields
        )
        return results

    async def get_user_live_posts_page(
        self,
        username: str,
        *,
        limit: int = 20,
        fields: str = USER_LIVE_FIELDS,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None, bool]:
        """One page of user-live posts: (results, next_page_cursor, has_more).

        Cursor pagination verified live (audit §Capabilities): pass the previous
        page's next_page_cursor back as `cursor`; a non-token value -> 500.
        """
        clean_username = username.lstrip("@").strip()
        params: dict[str, str | int] = {"fields": fields, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = await self._client.get(
            f"/api/data/twitter/posts/users/{clean_username}/live",
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        return results, data.get("next_page_cursor"), bool(data.get("has_more"))

    async def search_live_posts(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """Search public X posts in real time by keyword query."""
        params = {
            "q": query,
            "limit": limit,
        }
        response = await self._client.get(
            "/api/data/twitter/posts/live",
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("results") or []

