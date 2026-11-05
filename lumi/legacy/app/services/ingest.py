"""Shared ingestion policy for all three own-post paths.

The audit (docs/profile_extract_audit.md §7) showed the paths could drift —
PFM reads ``like_count|likes`` while Xpoz reads ``likeCount``. Every path now
normalizes through ``RawItem`` (mappers) and writes through ``store_raw_item``
so classification, routing, snapshot policy, provenance, and missing-metric
handling are identical everywhere.

Routes:
  PFM paged backfill  -> backfill_profile_posts (services/pfm.py)
  PFM feed (analytics)-> _ingest_pfm_feed       (services/analytics.py)
  Xpoz user-live      -> _ingest_xpoz_user_posts (services/analytics.py)

Rules (profile_extract_fixes.md Step 2):
  - missing metric -> None/NULL, NEVER 0 (finding 1: 24 fabricated all-zero rows)
  - self-replies -> posts (kind="original" + thread fields), not user_activity
  - kind_source "api" when structural flags are present, else "heuristic"
  - every snapshot records age_hours; skip unchanged+stale per should_insert_snapshot
  - last_seen_at + two-consecutive-miss -> is_deleted_suspect (<30d posts only)
  - one profile_snapshots row per ingestion pass
  - timezone inferred weakly from the posting-hour histogram; user confirmation wins
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.analysis.metrics import (
    metrics_tuple,
    should_insert_snapshot,
    snapshot_age_hours,
)
from app.models.activity import UserActivity
from app.models.post import MetricSnapshot, Post
from app.models.profile import Profile, ProfileSnapshot

DELETION_WINDOW = timedelta(days=30)
MIN_TZ_POSTS = 10  # weak inference needs at least this many originals
TRUNCATION_MIN_LEN = 270  # see detect_truncation / audit §4


# --------------------------------------------------------------------------
# Classification (moved here from pfm.py so ingest can be the base module;
# pfm re-exports for existing importers/tests)
# --------------------------------------------------------------------------
def classify_post_kind(caption: str | None) -> str:
    """Classify a feed item as "reply", "retweet", or "original" by text shape.

    PFM gives no structural flags on feed items, so we go by shape:
    replies/mention-openers ("@handle ...") and retweets ("RT @user: ...",
    "RT: ...") are not authentic originals. Quotes carry the creator's own
    commentary and classify as "original".
    """
    text = (caption or "").strip().lower()
    if text.startswith("@"):
        return "reply"
    if text.startswith(("rt ", "rt@", "rt:")):
        return "retweet"
    return "original"


def is_authentic_original(caption: str | None) -> bool:
    """True when a caption looks like the creator's own original post (or a quote).

    Replies and retweets are kept out of `posts` (voice/caption material) and
    stored in `user_activity` instead — see `upsert_user_activity`.
    """
    return bool((caption or "").strip()) and classify_post_kind(caption) == "original"


def detect_truncation(caption: str | None) -> bool:
    """Flag text that looks cut off (excluded from hook/body analysis).

    Audit §4 found zero instances today (long posts arrive whole), but nothing
    guarantees `text` completeness, and there is no full-text fetch endpoint yet
    (docs/xpoz_capabilities.md is niche Prompt 1 Step 0's deliverable) — so a
    flagged post keeps its flag and stays out of analysis instead.
    """
    text = (caption or "").rstrip()
    if len(text) < TRUNCATION_MIN_LEN or len(text) > 280:
        return False
    tail = text.lower()
    return tail.endswith(("…", "...")) or "http" in tail[-40:]


# --------------------------------------------------------------------------
# Normalized item + classification decision
# --------------------------------------------------------------------------
@dataclass
class PostFlags:
    """Structural flags when the source provides them (Xpoz user-live does).

    All-None means the source gave no structural info -> heuristic fallback.
    """

    is_retweet: bool | None = None
    reply_to_tweet_id: str | None = None
    reply_to_user_id: str | None = None
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


@dataclass
class IngestDecision:
    kind: str  # "original" | "reply" | "retweet"
    kind_source: str  # "api" | "heuristic"
    to_activity: bool  # True -> user_activity, False -> posts
    conversation_id: str | None = None
    is_thread_head: bool | None = None  # exact position comes from rethread_conversation
    thread_position: int | None = None


def classify_post_item(
    caption: str | None,
    *,
    flags: PostFlags | None = None,
    user_handle: str | None = None,
) -> IngestDecision:
    """Route one item using API flags when present, text heuristics otherwise.

    Self-replies (parent author == the user) become kind="original" with thread
    fields and go to posts, NOT user_activity (Step 2). kind_source records
    which basis decided.
    """
    if flags is not None and flags.has_structure():
        if flags.is_retweet:
            return IngestDecision(kind="retweet", kind_source="api", to_activity=True)
        if flags.reply_to_tweet_id:
            handle = (user_handle or "").lstrip("@").lower()
            parent = (flags.reply_to_username or "").lstrip("@").lower()
            if handle and parent == handle:
                # replying to own post = thread continuation -> posts
                return IngestDecision(
                    kind="original",
                    kind_source="api",
                    to_activity=False,
                    conversation_id=flags.conversation_id,
                    is_thread_head=False,
                )
            return IngestDecision(kind="reply", kind_source="api", to_activity=True)
        # standalone post or quote (own commentary) — both are authentic originals
        return IngestDecision(
            kind="original",
            kind_source="api",
            to_activity=False,
            conversation_id=flags.conversation_id,
            is_thread_head=True if not flags.conversation_id else None,  # rethread fixes it
        )

    # --- heuristic fallback (PFM items, or Xpoz without requested flags) ---
    # Note: a "@handle ..." opener classifies as "reply" here, including a
    # self-mention — without structural flags we cannot prove it is a thread
    # continuation, so it conservatively stays out of originals. Real self-reply
    # routing (parent author == user -> posts + thread fields) is the API path
    # above, driven by reply_to_username.
    kind = classify_post_kind(caption)
    return IngestDecision(kind=kind, kind_source="heuristic", to_activity=kind != "original")


# --------------------------------------------------------------------------
# Raw item + path mappers (one normalization per source)
# --------------------------------------------------------------------------
@dataclass
class RawItem:
    platform_post_id: str
    caption: str
    published_at: datetime
    metrics: dict[str, int | None] = field(default_factory=dict)
    flags: PostFlags | None = None


def _first_int(data: dict, *keys: str) -> int | None:
    """First present key as int; missing -> None (NEVER 0)."""
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _parse_dt(value) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.now(UTC)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def map_pfm_item(item: dict) -> RawItem | None:
    platform_id = str(item.get("id") or item.get("platform_post_id") or "")
    caption = (item.get("caption") or item.get("text") or "").strip()
    if not platform_id or not caption:
        return None
    raw = item.get("metrics") or item.get("public_metrics") or {}
    return RawItem(
        platform_post_id=platform_id,
        caption=caption,
        published_at=_parse_dt(item.get("posted_at") or item.get("published_at")),
        metrics={
            "likes": _first_int(raw, "like_count", "likes"),
            "comments": _first_int(raw, "reply_count", "comments"),
            "shares": _first_int(raw, "retweet_count", "shares"),
            "views": _first_int(raw, "impression_count", "views"),
            "quotes": _first_int(raw, "quote_count", "quotes"),
            "bookmarks": _first_int(raw, "bookmark_count", "bookmarks"),
        },
        flags=None,  # PFM carries no structural flags (kept from classify_post_kind docs)
    )


def map_xpoz_item(item: dict) -> RawItem | None:
    platform_id = str(item.get("id") or "")
    caption = (item.get("text") or "").strip()
    if not platform_id or not caption:
        return None
    return RawItem(
        platform_post_id=platform_id,
        caption=caption,
        published_at=_parse_dt(item.get("createdAt")),
        metrics={
            "likes": _first_int(item, "likeCount"),
            "comments": _first_int(item, "replyCount"),
            "shares": _first_int(item, "retweetCount"),
            "views": _first_int(item, "impressionCount"),
            "quotes": _first_int(item, "quoteCount"),
            "bookmarks": _first_int(item, "bookmarkCount"),
        },
        flags=PostFlags(
            is_retweet=item.get("isRetweet"),
            reply_to_tweet_id=str(item["replyToTweetId"]) if item.get("replyToTweetId") else None,
            reply_to_user_id=str(item["replyToUserId"]) if item.get("replyToUserId") else None,
            reply_to_username=item.get("replyToUsername") or None,
            quoted_tweet_id=str(item["quotedTweetId"]) if item.get("quotedTweetId") else None,
            conversation_id=str(item["conversationId"]) if item.get("conversationId") else None,
        ),
    )


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
async def upsert_user_activity(
    session,
    profile_id: int,
    platform_post_id: str,
    kind: str,
    caption: str,
    published_at: datetime | None = None,
    platform: str = "x",
    metrics: dict[str, int | None] | None = None,
    source: str | None = None,
) -> bool:
    """Store a reply/retweet in user_activity (metrics when provided). True = new."""
    existing = (
        await session.exec(
            select(UserActivity).where(
                UserActivity.profile_id == profile_id,
                UserActivity.platform_post_id == platform_post_id,
            )
        )
    ).first()
    if existing is not None:
        if metrics:
            for column, key in (("likes", "likes"), ("replies", "comments"), ("views", "views")):
                value = metrics.get(key)
                if value is not None and getattr(existing, column) != value:
                    setattr(existing, column, value)
        if source and not existing.source:
            existing.source = source
        return False
    session.add(
        UserActivity(
            profile_id=profile_id,
            platform=platform,
            platform_post_id=platform_post_id,
            kind=kind,
            caption=caption,
            published_at=published_at or datetime.now(UTC),
            likes=(metrics or {}).get("likes"),
            replies=(metrics or {}).get("comments"),
            views=(metrics or {}).get("views"),
            source=source,
        )
    )
    await session.flush()
    return True


async def rethread_conversation(session, profile_id: int, conversation_id: str) -> None:
    """Renumber thread fields for a conversation by publish order (ingest order
    is newest-first, so positions must come from time, not arrival)."""
    posts = (
        await session.exec(
            select(Post)
            .where(Post.profile_id == profile_id, Post.conversation_id == conversation_id)
            .order_by(Post.published_at)
        )
    ).all()
    for position, post in enumerate(posts, start=1):
        post.thread_position = position
        post.is_thread_head = position == 1


@dataclass
class StoreResult:
    """What store_raw_item did with one item."""

    route: str  # "post" | "activity" | "skipped"
    created: bool = False


async def store_raw_item(
    session,
    profile: Profile,
    raw: RawItem,
    *,
    source: str,
    now: datetime | None = None,
) -> StoreResult:
    """Classify + route one normalized item. Returns its route + created flag."""
    if profile.id is None:
        return StoreResult(route="skipped")
    now = now or datetime.now(UTC)
    decision = classify_post_item(
        raw.caption, flags=raw.flags, user_handle=profile.handle
    )

    if decision.to_activity:
        inserted = await upsert_user_activity(
            session,
            profile.id,
            raw.platform_post_id,
            decision.kind,
            raw.caption,
            published_at=raw.published_at,
            platform=profile.platform or "x",
            metrics=raw.metrics,
            source=source,
        )
        return StoreResult(route="activity", created=inserted)

    post = (
        await session.exec(
            select(Post).where(
                Post.profile_id == profile.id, Post.platform_post_id == raw.platform_post_id
            )
        )
    ).first()
    created = post is None
    if post is None:
        post = Post(
            profile_id=profile.id,
            platform_post_id=raw.platform_post_id,
            caption=raw.caption,
            published_at=raw.published_at,
            source=source,
            kind=decision.kind,
            kind_source=decision.kind_source,
            conversation_id=decision.conversation_id,
            thread_position=decision.thread_position,
            is_thread_head=decision.is_thread_head,
            text_truncated=detect_truncation(raw.caption),
            last_seen_at=now,
        )
        session.add(post)
        await session.flush()
    else:
        post.last_seen_at = now
        if detect_truncation(raw.caption):
            post.text_truncated = True  # sticky flag: never cleared without a fetch
        if post.kind is None:
            post.kind = decision.kind
            post.kind_source = decision.kind_source
        if post.conversation_id is None and decision.conversation_id:
            post.conversation_id = decision.conversation_id

    if post.conversation_id:
        await rethread_conversation(session, profile.id, post.conversation_id)

    # --- snapshot under the shared policy ---
    age_hours = (now - raw.published_at).total_seconds() / 3600.0
    prev = (
        await session.exec(
            select(MetricSnapshot)
            .where(MetricSnapshot.post_id == post.id)
            .order_by(MetricSnapshot.captured_at.desc())
        )
    ).first()
    new_metrics = (
        raw.metrics.get("likes"),
        raw.metrics.get("comments"),
        raw.metrics.get("shares"),
        raw.metrics.get("views"),
    )
    if prev is not None and prev.captured_at == now:
        return StoreResult(route="post", created=created)  # same-pass duplicate: unique (post_id, captured_at) guard
    if should_insert_snapshot(
        snapshot_age_hours(post, prev) if prev is not None else None,
        metrics_tuple(prev) if prev is not None else None,
        new_metrics,
        age_hours,
    ):
        session.add(
            MetricSnapshot(
                post_id=post.id,
                captured_at=now,
                likes=new_metrics[0],
                comments=new_metrics[1],
                shares=new_metrics[2],
                views=new_metrics[3],
                age_hours=round(age_hours, 4),
                source=source,
            )
        )
        await session.flush()
    return StoreResult(route="post", created=created)


# --------------------------------------------------------------------------
# Pass bookkeeping: last_seen_at, deletion suspects, one profile snapshot,
# weak timezone inference
# --------------------------------------------------------------------------
def is_second_miss(
    last_seen_at: datetime | None,
    prev_pass_at: datetime | None,
    published_at: datetime,
    *,
    now: datetime,
    pass_complete: bool,
    oldest_fetched: datetime | None = None,
    newest_fetched: datetime | None = None,
) -> bool:
    """True when a post inside the 30d window missed two consecutive complete passes.

    Bracket guard (order-agnostic): the pass must have fetched posts BOTH older
    and newer than this post, otherwise "missing" only means "outside the fetched
    slice" — feed order is unverified (audit §6), so this prevents false deletions.
    """
    if not pass_complete or prev_pass_at is None:
        return False  # incomplete pass or first pass ever: no two-miss evidence
    if last_seen_at is None:
        return False  # never seen — cannot prove two misses (conservative)
    if now - published_at > DELETION_WINDOW:
        return False  # only posts inside the last 30d are tracked
    if oldest_fetched is None or newest_fetched is None:
        return False
    if not (oldest_fetched < published_at < newest_fetched):
        return False  # fetch slice doesn't span this post's publish time
    return last_seen_at < prev_pass_at


def pass_reached_window(oldest_published: datetime | None, *, now: datetime | None = None) -> bool:
    """A newest-first fetch covered the 30d deletion window when its oldest
    item is older than 30d (or it exhausted the source)."""
    now = now or datetime.now(UTC)
    return oldest_published is not None and oldest_published < now - DELETION_WINDOW


def infer_timezone(published_posts: list[datetime]) -> str | None:
    """Weak inference: mode of the UTC posting hour, anchored to ~21:00 local
    evening. timezone_source="inferred" — the user must be able to confirm it."""
    if len(published_posts) < MIN_TZ_POSTS:
        return None
    counts = Counter(dt.hour for dt in published_posts)
    mode = max(sorted(counts), key=lambda h: counts[h])  # deterministic tie: lowest hour
    offset = ((21 - mode + 12) % 24) - 12  # range -12..+11
    return f"UTC{offset:+03d}:00"


def maybe_update_timezone(profile: Profile, published_posts: list[datetime]) -> str | None:
    """Set profile.timezone from the histogram. user_confirmed always wins."""
    if profile.timezone_source == "user_confirmed":
        return None
    tz = infer_timezone(published_posts)
    if tz is None or (profile.timezone == tz and profile.timezone_source == "inferred"):
        return None
    profile.timezone = tz
    profile.timezone_source = "inferred"
    return tz


def confirm_timezone(profile: Profile, timezone: str) -> None:
    """User confirmation: sets the value and locks it against re-inference."""
    profile.timezone = timezone
    profile.timezone_source = "user_confirmed"


async def finalize_ingest_pass(
    session,
    profile: Profile,
    *,
    fetched_ids: set[str],
    source: str,
    pass_started: datetime,
    pass_complete: bool,
    fetched_window: tuple[datetime, datetime] | None = None,
) -> dict:
    """End-of-pass bookkeeping. Caller commits.

    - last_seen_at = pass time for every post actually fetched
    - is_deleted_suspect after two consecutive misses (only complete passes
      count, and only when fetched_window brackets the post — see is_second_miss)
    - exactly one profile_snapshots row per pass (followers/following stay
      NULL until a profile-lookup capability is verified — never fabricated)
    - weak timezone inference (never overwrites user_confirmed)
    """
    if profile.id is None:
        return {"error": "profile has no id"}

    prev_snap = (
        await session.exec(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.profile_id == profile.id, ProfileSnapshot.captured_at < pass_started)
            .order_by(ProfileSnapshot.captured_at.desc())
        )
    ).first()
    prev_pass_at = prev_snap.captured_at if prev_snap is not None else None
    oldest_fetched = fetched_window[0] if fetched_window else None
    newest_fetched = fetched_window[1] if fetched_window else None

    posts = (await session.exec(select(Post).where(Post.profile_id == profile.id))).all()
    seen = 0
    flagged = 0
    for post in posts:
        if post.platform_post_id in fetched_ids:
            post.last_seen_at = pass_started
            seen += 1
        elif is_second_miss(
            post.last_seen_at,
            prev_pass_at,
            post.published_at,
            now=pass_started,
            pass_complete=pass_complete,
            oldest_fetched=oldest_fetched,
            newest_fetched=newest_fetched,
        ):
            if not post.is_deleted_suspect:
                post.is_deleted_suspect = True
                flagged += 1

    session.add(
        ProfileSnapshot(
            profile_id=profile.id,
            captured_at=pass_started,
            followers=None,  # unknown until profile lookup is verified
            following=None,
            source=source,
        )
    )
    maybe_update_timezone(profile, [p.published_at for p in posts])
    await session.flush()
    return {"seen": seen, "flagged_deleted": flagged, "pass_complete": pass_complete}
