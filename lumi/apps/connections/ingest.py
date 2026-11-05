"""Pure ingestion policy: classify a post and map provider items to ``PostIn``.

Ported from the legacy ``legacy/app/services/ingest.py`` and ``pfm.py`` (same folder) without any database code. The
database side (``apps.profiles.services``) receives the ``PostIn`` objects produced here.

Rules that every path follows:

* A missing metric is ``None``, never 0. A zero would be a fabricated number.
* Structural flags from the API win over text heuristics. Heuristics are the fallback, because
  Post for Me gives no flags.
* A reply to the user's own post is a thread continuation: ``kind="original"`` with the
  conversation id, so it stays in ``posts``.
* A post without an id, text or a parsable date is dropped. A date is never invented.
* Media is mapped only when the source states its kind (PFM items with a type or MIME). A kind
  is never guessed from a URL. Xpoz sends bare URLs for X posts, so those become
  ``MediaRef(kind=None)`` (ports 1.9, ``post_media.kind`` is nullable since ``profiles.0002``).
  ``None`` means unknown, never "image". Thumbnails are not carried.
* Provider payload fields that are not mapped here (tokens, raw ids of other users) are not
  carried over.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from lumi_ai.ports import MediaRef, Platform, PostIn, PostKind, PostMetrics

from .providers.routes import PFM_PLATFORMS

TRUNCATION_MIN_LEN = 270
TRUNCATION_MAX_LEN = 280
ACTIVITY_KINDS = frozenset({"reply", "retweet"})


def classify_post_kind(caption: str | None) -> str:
    """Classify by text shape: ``reply``, ``retweet`` or ``original``.

    A leading ``@`` is a reply. ``RT @user``, ``RT@`` and ``RT:`` are retweets. A quote
    carries the author's own words, so it counts as an original.
    """
    text = (caption or "").strip().lower()
    if text.startswith("@"):
        return "reply"
    if text.startswith(("rt ", "rt@", "rt:")):
        return "retweet"
    return "original"


def is_authentic_original(caption: str | None) -> bool:
    """True when the text looks like the creator's own post. Replies and retweets are not."""
    return bool((caption or "").strip()) and classify_post_kind(caption) == "original"


def detect_truncation(caption: str | None) -> bool:
    """Flag text that looks cut off (an ellipsis or a trailing link near the 280 limit)."""
    text = (caption or "").rstrip()
    if len(text) < TRUNCATION_MIN_LEN or len(text) > TRUNCATION_MAX_LEN:
        return False
    tail = text.lower()
    return tail.endswith(("…", "...")) or "http" in tail[-40:]


def routes_to_activity(kind: str | None) -> bool:
    """Replies and retweets go to the activity table, everything else to posts."""
    return kind in ACTIVITY_KINDS


@dataclass(frozen=True, slots=True)
class PostFlags:
    """Structural flags when the source reports them. All ``None`` means no structure."""

    is_retweet: bool | None = None
    reply_to_tweet_id: str | None = None
    reply_to_username: str | None = None
    quoted_tweet_id: str | None = None
    conversation_id: str | None = None

    def has_structure(self) -> bool:
        return bool(
            self.is_retweet is not None
            or self.reply_to_tweet_id
            or self.quoted_tweet_id
            or self.conversation_id
        )


@dataclass(frozen=True, slots=True)
class Classification:
    kind: PostKind
    kind_source: str  # "api" or "heuristic"
    conversation_id: str | None = None


def classify_post(
    caption: str | None,
    *,
    flags: PostFlags | None = None,
    user_handle: str | None = None,
) -> Classification:
    if flags is not None and flags.has_structure():
        if flags.is_retweet:
            return Classification("retweet", "api", flags.conversation_id)
        if flags.reply_to_tweet_id:
            me = (user_handle or "").lstrip("@").lower()
            parent = (flags.reply_to_username or "").lstrip("@").lower()
            if me and parent == me:
                return Classification("original", "api", flags.conversation_id)
            return Classification("reply", "api", flags.conversation_id)
        if flags.quoted_tweet_id:
            return Classification("quote", "api", flags.conversation_id)
        return Classification("original", "api", flags.conversation_id)
    return Classification(cast(PostKind, classify_post_kind(caption)), "heuristic")


def _int(value: Any) -> int | None:
    """An int, or ``None`` when absent or not numeric. Booleans are not counts."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first(data: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        number = _int(data.get(key))
        if number is not None:
            return number
    return None


def _from_epoch(value: float) -> datetime | None:
    """A POSIX timestamp in seconds (or milliseconds above 1e11) as an aware UTC datetime."""
    if value <= 0:
        return None
    if value > 1e11:
        value /= 1000.0
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    """An ISO-8601 string or a POSIX timestamp. Xpoz sends ``createdAt`` as either one,
    depending on the platform (X and Instagram as ISO text, TikTok as epoch seconds)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) in (10, 13):
        return _from_epoch(float(text))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _handle(value: Any) -> str | None:
    text = _text(value)
    return text.lstrip("@").lower() if text else None


def pfm_metrics(platform: str, metrics: Any) -> PostMetrics:
    """Map the platform-specific PFM metrics object. Unknown shapes give an all-None result."""
    if not isinstance(metrics, Mapping):
        return PostMetrics()
    if platform == "x":
        public = metrics.get("public_metrics")
        source = public if isinstance(public, Mapping) else metrics
        organic = metrics.get("organic_metrics")
        organic = organic if isinstance(organic, Mapping) else {}
        views = _first(source, "impression_count")
        if views is None:
            views = _first(organic, "impression_count")
        return PostMetrics(
            views=views,
            likes=_first(source, "like_count", "likes"),
            comments=_first(source, "reply_count", "comments"),
            shares=_first(source, "retweet_count", "shares"),
            bookmarks=_first(source, "bookmark_count", "bookmarks"),
            quotes=_first(source, "quote_count", "quotes"),
        )
    if platform == "instagram":
        return PostMetrics(
            views=_first(metrics, "views"),
            likes=_first(metrics, "likes"),
            comments=_first(metrics, "comments"),
            shares=_first(metrics, "shares"),
            bookmarks=_first(metrics, "saved"),
        )
    if platform == "tiktok":
        return PostMetrics(
            views=_first(metrics, "view_count"),
            likes=_first(metrics, "like_count"),
            comments=_first(metrics, "comment_count"),
            shares=_first(metrics, "share_count"),
        )
    if platform == "facebook":
        return PostMetrics(
            views=_first(metrics, "media_views"),
            likes=_first(metrics, "reactions_total"),
            comments=_first(metrics, "comments"),
            shares=_first(metrics, "shares"),
        )
    if platform == "linkedin":
        return PostMetrics(
            views=_first(metrics, "impressionCount"),
            likes=_first(metrics, "likeCount"),
            comments=_first(metrics, "commentCount"),
            shares=_first(metrics, "shareCount"),
        )
    return PostMetrics()


_MEDIA_URL_KEYS = ("url", "media_url", "source_url")
_MEDIA_KIND_KEYS = ("type", "kind", "media_type", "mime_type", "content_type")


def _media_kind(value: Any) -> str | None:
    """``image``, ``video`` or ``gif`` from a type word or a MIME type; ``None`` otherwise."""
    text = _text(value)
    if text is None:
        return None
    text = text.lower()
    if text in ("gif", "animated_gif") or text.endswith("/gif"):
        return "gif"
    head = text.split("/", 1)[0]
    if head in ("image", "photo", "picture"):
        return "image"
    if head in ("video", "reel"):
        return "video"
    return None


def pfm_media(raw: Any) -> tuple[MediaRef, ...]:
    """Media of a PFM item. Entries without an http(s) url or a stated kind are dropped."""
    if not isinstance(raw, list):
        return ()
    out: list[MediaRef] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        url = next((u for k in _MEDIA_URL_KEYS if (u := _text(entry.get(k)))), None)
        kind = next(
            (m for k in _MEDIA_KIND_KEYS if (m := _media_kind(entry.get(k)))), None
        )
        if url is None or kind is None or not url.startswith(("https://", "http://")):
            continue
        out.append(MediaRef(kind=cast(Any, kind), url=url))
    return tuple(out)


def xpoz_media(raw: Any) -> tuple[MediaRef, ...]:
    """X media from Xpoz ``mediaUrls``: bare URLs, so the kind stays unknown (``None``)."""
    if not isinstance(raw, list):
        return ()
    seen: dict[str, None] = {}
    for entry in raw:
        url = _text(entry)
        if url is not None and url.startswith(("https://", "http://")):
            seen.setdefault(url)
    return tuple(MediaRef(kind=None, url=url) for url in seen)


def map_pfm_item(
    item: Mapping[str, Any], *, handle: str | None = None
) -> PostIn | None:
    """Map one ``PlatformPostDto`` from the PFM feed. ``None`` when it cannot be used."""
    platform = _text(item.get("platform"))
    if platform is None or platform.lower() not in PFM_PLATFORMS:
        return None
    platform = platform.lower()
    external_id = _text(item.get("platform_post_id")) or _text(item.get("id"))
    text = _text(item.get("caption")) or _text(item.get("text"))
    published = parse_datetime(item.get("posted_at") or item.get("published_at"))
    if external_id is None or text is None or published is None:
        return None
    verdict = classify_post(text)  # PFM sends no structural flags
    return PostIn(
        platform=cast(Platform, platform),
        external_id=external_id,
        text=text,
        published_at=published,
        author_handle=_handle(handle),
        kind=verdict.kind,
        url=_text(item.get("platform_url")),
        metrics=pfm_metrics(platform, item.get("metrics")),
        source="pfm",
        text_truncated=detect_truncation(text),
        media=pfm_media(item.get("media")),
    )


def _post_url(platform: str, item: Mapping[str, Any], post_id: str, author: str | None) -> str | None:
    """The public URL of a mapped post, from the row when it reports one."""
    given = _text(item.get("postUrl")) or _text(item.get("codeUrl"))
    if given:
        return given
    permalink = _text(item.get("permalink"))
    if platform == "reddit":
        return f"https://www.reddit.com{permalink}" if permalink else None
    if not author:
        return None
    if platform == "instagram":
        return f"https://www.instagram.com/{author}/p/{post_id}/"
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{author}/video/{post_id}"
    return None


def map_xpoz_platform_post(
    platform: str, item: Mapping[str, Any], *, user_handle: str | None = None
) -> PostIn | None:
    """Map one post row from Xpoz on any platform with a post endpoint.

    X rows go through ``map_xpoz_post``. Instagram, TikTok and Reddit rows name their own
    fields (``caption`` / ``description`` / ``title`` + ``selftext``), so each is read here.
    """
    if platform == "x":
        return map_xpoz_post(item, user_handle=user_handle)
    external_id = _text(str(item["id"])) if item.get("id") is not None else None
    published = parse_datetime(item.get("createdAt"))
    author = _handle(item.get("username") or item.get("authorUsername")) or _handle(
        user_handle
    )
    if platform == "instagram":
        text = _text(item.get("caption"))
        metrics = PostMetrics(
            views=_first(item, "videoPlayCount"),
            likes=_first(item, "likeCount"),
            comments=_first(item, "commentCount"),
            shares=_first(item, "reshareCount"),
            bookmarks=_first(item, "saveCount"),
        )
        avatar = _text(item.get("profilePicUrl"))
    elif platform == "tiktok":
        text = _text(item.get("description"))
        metrics = PostMetrics(
            views=_first(item, "playCount"),
            likes=_first(item, "likeCount"),
            comments=_first(item, "commentCount"),
            shares=_first(item, "forwardCount"),
            bookmarks=_first(item, "collectCount"),
        )
        avatar = None
    elif platform == "reddit":
        title = _text(item.get("title"))
        body = _text(item.get("selftext"))
        text = "\n\n".join(part for part in (title, body) if part)
        # Reddit has no likes: ``score`` is upvotes minus downvotes, the closest honest number.
        metrics = PostMetrics(
            likes=_first(item, "score"), comments=_first(item, "commentsCount")
        )
        avatar = None
    else:
        return None
    if external_id is None or text is None or published is None:
        return None
    return PostIn(
        platform=cast(Any, platform),
        external_id=external_id,
        text=text,
        published_at=published,
        author_handle=author,
        kind=cast(Any, classify_post_kind(text)),
        url=_post_url(platform, item, external_id, author),
        metrics=metrics,
        source="xpoz",
        text_truncated=detect_truncation(text),
        author_avatar_url=avatar,
    )


def map_xpoz_post(
    item: Mapping[str, Any], *, user_handle: str | None = None
) -> PostIn | None:
    """Map one X post from Xpoz. ``user_handle`` enables self-reply thread detection."""
    external_id = _text(str(item["id"])) if item.get("id") is not None else None
    text = _text(item.get("text"))
    published = parse_datetime(item.get("createdAt"))
    if external_id is None or text is None or published is None:
        return None
    author = _handle(item.get("authorUsername")) or _handle(user_handle)
    flags = PostFlags(
        is_retweet=item.get("isRetweet")
        if isinstance(item.get("isRetweet"), bool)
        else None,
        reply_to_tweet_id=_text(str(item["replyToTweetId"]))
        if item.get("replyToTweetId")
        else None,
        reply_to_username=_text(item.get("replyToUsername")),
        quoted_tweet_id=_text(str(item["quotedTweetId"]))
        if item.get("quotedTweetId")
        else None,
        conversation_id=_text(str(item["conversationId"]))
        if item.get("conversationId")
        else None,
    )
    verdict = classify_post(text, flags=flags, user_handle=user_handle or author)
    return PostIn(
        platform="x",
        external_id=external_id,
        text=text,
        published_at=published,
        author_handle=author,
        kind=verdict.kind,
        url=f"https://x.com/{author}/status/{external_id}" if author else None,
        metrics=PostMetrics(
            views=_first(item, "impressionCount"),
            likes=_first(item, "likeCount"),
            comments=_first(item, "replyCount"),
            shares=_first(item, "retweetCount"),
            bookmarks=_first(item, "bookmarkCount"),
            quotes=_first(item, "quoteCount"),
        ),
        conversation_id=verdict.conversation_id,
        language=_text(item.get("lang")),
        source="xpoz",
        text_truncated=detect_truncation(text),
        media=xpoz_media(item.get("mediaUrls")),
    )
