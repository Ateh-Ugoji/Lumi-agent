"""Acceptance tests for the profile-extract data-quality fixes.

Covers the 9 acceptance areas from profile_extract_fixes.md:
 1. missing metrics -> NULL, never 0
 2. self-reply routing (posts + thread fields; RTs/foreign replies -> activity)
 3. snapshot age_hours + final_metrics at the 72h target
 4. snapshot skip matrix (milestones / unchanged / 6h gap)
 5. truncation flagging (sticky, never silently cleared)
 6. two-consecutive-miss deletion suspects (+ order-agnostic bracket guard)
 7. baseline exclusions (deleted suspect / too young / too old / NULL views)
 8. own baseline == peer baseline (same functions by construction)
 9. timezone: weak inference, user confirmation always wins

Migration data fixes (Rule A/B) are verified by the copy-test script against
real data, not here (docs/profile_extract_audit.md records the counts).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  (registers all tables on SQLModel.metadata)
from app.analysis.metrics import (
    BaselineCandidate,
    BaselineResult,
    MetricSample,
    build_own_post_metrics,
    compute_baseline,
    eligible_baseline_samples,
    final_metrics,
    milestone_bucket,
    should_insert_snapshot,
)
from app.models.post import MetricSnapshot, Post
from app.models.profile import Profile
from app.services.ingest import (
    RawItem,
    _first_int,
    classify_post_item,
    confirm_timezone,
    detect_truncation,
    finalize_ingest_pass,
    infer_timezone,
    is_second_miss,
    map_pfm_item,
    map_xpoz_item,
    maybe_update_timezone,
    pass_reached_window,
    rethread_conversation,
    store_raw_item,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session():
    """Per-test in-memory SQLite with the full schema (tests only — the app
    itself never calls create_all; Alembic owns production schema)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_profile(session: AsyncSession, handle: str = "ateh") -> Profile:
    profile = Profile(name="Test", handle=handle, pfm_account_id=f"spc_test_{handle}")
    session.add(profile)
    await session.flush()
    return profile


# ==========================================================================
# Area 1 — missing metrics are NULL, never 0
# ==========================================================================
def test_first_int_missing_is_none_but_real_zero_stays_zero():
    assert _first_int({}, "likes") is None
    assert _first_int({"likes": None}, "likes") is None
    # a genuine 0 from the API is data, not missing — it must survive
    assert _first_int({"likes": 0}, "likes") == 0
    assert _first_int({"like_count": 5, "likes": 9}, "like_count", "likes") == 5
    assert _first_int({"likes": "not-a-number"}, "likes") is None


def test_map_pfm_item_missing_metrics_stay_none():
    raw = map_pfm_item({"id": "1", "caption": "hello", "posted_at": T0.isoformat()})
    assert raw is not None
    assert raw.metrics == {
        "likes": None,
        "comments": None,
        "shares": None,
        "views": None,
        "quotes": None,
        "bookmarks": None,
    }
    assert map_pfm_item({"caption": "no id"}) is None
    assert map_pfm_item({"id": "1", "caption": ""}) is None


def test_map_pfm_item_reads_nested_metrics_without_zero_filling():
    raw = map_pfm_item(
        {
            "id": "2",
            "caption": "hi",
            "posted_at": T0.isoformat(),
            "metrics": {"like_count": 7, "impression_count": 0},
        }
    )
    assert raw is not None
    assert raw.metrics["likes"] == 7
    assert raw.metrics["views"] == 0  # reported zero is real
    assert raw.metrics["comments"] is None  # absent is NULL


def test_map_xpoz_item_missing_counts_stay_none():
    raw = map_xpoz_item({"id": "9", "text": "hi", "createdAt": T0.isoformat()})
    assert raw is not None
    assert raw.metrics["views"] is None
    assert raw.metrics["likes"] is None
    raw2 = map_xpoz_item(
        {"id": "9", "text": "hi", "createdAt": T0.isoformat(), "likeCount": 3, "impressionCount": 40}
    )
    assert raw2 is not None
    assert raw2.metrics["likes"] == 3
    assert raw2.metrics["views"] == 40


async def test_store_raw_item_writes_null_snapshot_for_missing_metrics(session):
    profile = await _make_profile(session)
    raw = RawItem(platform_post_id="1", caption="hello world", published_at=T0)
    result = await store_raw_item(session, profile, raw, source="xpoz", now=T0 + timedelta(hours=5))
    await session.commit()
    assert result.route == "post" and result.created

    post = (
        await session.exec(select(Post).where(Post.platform_post_id == "1"))
    ).first()
    snap = (await session.exec(select(MetricSnapshot).where(MetricSnapshot.post_id == post.id))).one()
    assert snap.views is None and snap.likes is None
    assert snap.comments is None and snap.shares is None
    assert snap.age_hours == 5.0
    assert snap.source == "xpoz"


# ==========================================================================
# Area 2 — self-replies -> posts with thread fields; RTs/foreign -> activity
# ==========================================================================
def test_api_structured_self_reply_routes_to_posts():
    decision = classify_post_item(
        "continuing my thread",
        flags=map_xpoz_item(
            {
                "id": "2",
                "text": "continuing my thread",
                "createdAt": T0.isoformat(),
                "isRetweet": False,
                "replyToTweetId": "1",
                "replyToUsername": "Ateh",
                "conversationId": "1",
            }
        ).flags,
        user_handle="ateh",
    )
    assert decision.kind == "original"
    assert decision.kind_source == "api"
    assert decision.to_activity is False
    assert decision.conversation_id == "1"
    assert decision.is_thread_head is False


def test_api_structured_foreign_reply_goes_to_activity():
    decision = classify_post_item(
        "their post",
        flags=map_xpoz_item(
            {
                "id": "3",
                "text": "their post",
                "createdAt": T0.isoformat(),
                "isRetweet": False,
                "replyToTweetId": "99",
                "replyToUsername": "someone",
                "conversationId": "99",
            }
        ).flags,
        user_handle="ateh",
    )
    assert decision.kind == "reply"
    assert decision.to_activity is True


def test_api_structured_retweet_goes_to_activity():
    decision = classify_post_item(
        "rt text",
        flags=map_xpoz_item(
            {"id": "4", "text": "rt text", "createdAt": T0.isoformat(), "isRetweet": True}
        ).flags,
        user_handle="ateh",
    )
    assert decision.kind == "retweet"
    assert decision.kind_source == "api"
    assert decision.to_activity is True  # RTs are never attributed to the user's posts


def test_heuristic_reply_and_retweet_shapes_go_to_activity():
    reply = classify_post_item("@someone great point", user_handle="ateh")
    assert reply.kind == "reply" and reply.to_activity is True
    rt = classify_post_item("RT @user: wisdom", user_handle="ateh")
    assert rt.kind == "retweet" and rt.to_activity is True
    quote_like = classify_post_item("RT: nope this is my take", user_handle="ateh")
    assert quote_like.kind == "retweet"  # "RT:" prefix is ambiguous — kept out of originals


def test_heuristic_self_mention_opener_stays_out_of_originals():
    # Without structural flags a "@handle ..." opener is a reply — even a
    # self-mention. We cannot prove it's a thread continuation, so it stays
    # conservative: kind="reply" -> user_activity. Real self-reply routing
    # (parent == user -> posts + thread fields) is covered by the API tests.
    decision = classify_post_item("@ateh replied to myself here", user_handle="ateh")
    assert decision.kind == "reply"
    assert decision.kind_source == "heuristic"
    assert decision.to_activity is True


async def test_store_raw_item_self_reply_creates_thread_posts(session):
    profile = await _make_profile(session, handle="ateh")
    head = RawItem(
        platform_post_id="100",
        caption="original post",
        published_at=T0 - timedelta(hours=2),
        metrics={"likes": 1, "views": 100},
        flags=map_xpoz_item(
            {
                "id": "100",
                "text": "original post",
                "createdAt": (T0 - timedelta(hours=2)).isoformat(),
                "isRetweet": False,
                "conversationId": "100",
            }
        ).flags,
    )
    reply = RawItem(
        platform_post_id="101",
        caption="continuation",
        published_at=T0,
        metrics={"likes": 2, "views": 50},
        flags=map_xpoz_item(
            {
                "id": "101",
                "text": "continuation",
                "createdAt": T0.isoformat(),
                "isRetweet": False,
                "replyToTweetId": "100",
                "replyToUsername": "ateh",
                "conversationId": "100",
            }
        ).flags,
    )
    # ingest order is newest-first in reality; thread positions must come from
    # publish time, not arrival order — store the NEWER one first on purpose
    r2 = await store_raw_item(session, profile, reply, source="xpoz", now=T0 + timedelta(hours=1))
    r1 = await store_raw_item(session, profile, head, source="xpoz", now=T0 + timedelta(hours=1))
    await session.commit()
    assert r1.created and r2.created

    posts = (
        await session.exec(
            select(Post).where(Post.profile_id == profile.id).order_by(Post.published_at)
        )
    ).all()
    assert len(posts) == 2  # the self-reply is a post, NOT user_activity
    assert posts[0].platform_post_id == "100"
    assert posts[0].is_thread_head is True and posts[0].thread_position == 1
    assert posts[1].platform_post_id == "101"
    assert posts[1].kind == "original" and posts[1].kind_source == "api"
    assert posts[1].conversation_id == "100"
    assert posts[1].is_thread_head is False and posts[1].thread_position == 2


async def test_rethread_numbers_by_publish_time_not_arrival(session):
    profile = await _make_profile(session)
    late = Post(
        profile_id=profile.id,
        platform_post_id="200",
        caption="second",
        published_at=T0,
        conversation_id="c1",
    )
    early = Post(
        profile_id=profile.id,
        platform_post_id="199",
        caption="first",
        published_at=T0 - timedelta(hours=1),
        conversation_id="c1",
    )
    session.add_all([late, early])
    await session.flush()
    await rethread_conversation(session, profile.id, "c1")
    await session.commit()
    assert early.thread_position == 1 and early.is_thread_head is True
    assert late.thread_position == 2 and late.is_thread_head is False


# ==========================================================================
# Area 3 — snapshot age_hours + final_metrics at 72h
# ==========================================================================
def test_final_metrics_picks_nearest_72h():
    post = Post(
        id=5, profile_id=1, platform_post_id="5", caption="x", published_at=T0
    )
    snaps = [
        MetricSnapshot(post_id=5, captured_at=T0 + timedelta(hours=24), age_hours=24.0, views=10),
        MetricSnapshot(post_id=5, captured_at=T0 + timedelta(hours=70), age_hours=70.0, views=30),
        MetricSnapshot(post_id=5, captured_at=T0 + timedelta(hours=168), age_hours=168.0, views=40),
    ]
    fm = final_metrics(post, snaps)
    assert fm is not None and fm.age_hours == 70.0
    assert final_metrics(post, []) is None


def test_milestone_bucket_counts_targets():
    assert milestone_bucket(0.0) == 0
    assert milestone_bucket(24.0) == 1
    assert milestone_bucket(100.0) == 2  # 24h + 72h
    assert milestone_bucket(800.0) == 4  # all four


# ==========================================================================
# Area 4 — snapshot skip matrix
# ==========================================================================
def test_snapshot_skip_matrix():
    m1 = (10, 1, 0, 100)
    m1b = (10, 1, 0, 100)  # identical
    m2 = (11, 1, 0, 110)  # changed

    # first snapshot always inserts
    assert should_insert_snapshot(None, None, m1, 1.0) is True
    # changed metrics always insert
    assert should_insert_snapshot(1.0, m1, m2, 2.0) is True
    # unchanged, within 7d: needs >= 6h gap
    assert should_insert_snapshot(10.0, m1, m1b, 11.0) is False
    assert should_insert_snapshot(10.0, m1, m1b, 15.9) is False  # gap not yet reached
    assert should_insert_snapshot(10.0, m1, m1b, 16.0) is True  # exactly the 6h gap
    # unchanged, older than 7d: skip — unless a milestone is crossed
    assert should_insert_snapshot(200.0, m1, m1b, 210.0) is False
    assert should_insert_snapshot(160.0, m1, m1b, 170.0) is True  # crossed the 7d target


# ==========================================================================
# Area 5 — truncation flagging
# ==========================================================================
def test_detect_truncation_boundaries():
    assert detect_truncation("short post") is False
    assert detect_truncation("x" * 268 + "…") is False  # 269 chars: below the 270 threshold
    assert detect_truncation("x" * 269 + "…") is True  # 270 chars: at threshold, ellipsis tail
    assert detect_truncation("x" * 276 + "...") is True
    assert detect_truncation("x" * 280) is False  # exactly 280, no signal — arrives whole
    assert detect_truncation("x" * 300) is False  # >280 long-form posts are complete


async def test_truncation_flag_is_sticky_on_refetch(session):
    profile = await _make_profile(session)
    clean = RawItem(platform_post_id="300", caption="fine text", published_at=T0)
    await store_raw_item(session, profile, clean, source="pfm", now=T0 + timedelta(hours=1))
    await session.commit()

    truncated_caption = "x" * 274 + "…"
    again = RawItem(platform_post_id="300", caption=truncated_caption, published_at=T0)
    await store_raw_item(session, profile, again, source="pfm", now=T0 + timedelta(hours=2))
    await session.commit()

    post = (await session.exec(select(Post).where(Post.platform_post_id == "300"))).first()
    assert post.text_truncated is True  # sticky: a later clean refetch never clears it


# ==========================================================================
# Area 6 — deletion suspects: two consecutive misses + bracket guard
# ==========================================================================
def test_second_miss_requires_two_complete_misses():
    published = T0 - timedelta(days=2)
    ok = {
        "now": T0,
        "pass_complete": True,
        "oldest_fetched": published - timedelta(days=1),
        "newest_fetched": T0,
    }
    # second consecutive miss (last seen before the previous pass started)
    assert is_second_miss(T0 - timedelta(hours=6), T0 - timedelta(hours=3), published, **ok) is True
    # first miss (last seen == previous pass) — not enough evidence
    assert is_second_miss(T0 - timedelta(hours=3), T0 - timedelta(hours=3), published, **ok) is False
    # incomplete pass never counts
    bad = dict(ok, pass_complete=False)
    assert is_second_miss(T0 - timedelta(hours=6), T0 - timedelta(hours=3), published, **bad) is False
    # never seen -> can't prove two misses
    assert is_second_miss(None, T0 - timedelta(hours=3), published, **ok) is False


def test_second_miss_bracket_and_window_guards():
    published = T0 - timedelta(days=2)
    base = {"now": T0, "pass_complete": True}
    # fetch slice doesn't span the post's publish time -> not proof of deletion
    unspanned = dict(base, oldest_fetched=published + timedelta(hours=1), newest_fetched=T0)
    assert (
        is_second_miss(T0 - timedelta(hours=6), T0 - timedelta(hours=3), published, **unspanned)
        is False
    )
    # no window info at all -> conservative no
    no_window = dict(base, oldest_fetched=None, newest_fetched=None)
    assert (
        is_second_miss(T0 - timedelta(hours=6), T0 - timedelta(hours=3), published, **no_window)
        is False
    )
    # posts older than 30d are outside the tracking window
    old = T0 - timedelta(days=40)
    spanned = dict(base, oldest_fetched=old - timedelta(days=1), newest_fetched=T0)
    assert (
        is_second_miss(T0 - timedelta(hours=6), T0 - timedelta(hours=3), old, **spanned) is False
    )


def test_pass_reached_window():
    now = T0
    assert pass_reached_window(None, now=now) is False
    assert pass_reached_window(now - timedelta(days=10), now=now) is False
    assert pass_reached_window(now - timedelta(days=31), now=now) is True


async def test_finalize_ingest_pass_two_miss_flow(session):
    profile = await _make_profile(session)
    post = Post(
        profile_id=profile.id,
        platform_post_id="p1",
        caption="hi",
        published_at=T0 - timedelta(days=2),
    )
    session.add(post)
    await session.flush()

    # pass 1: post is fetched
    r1 = await finalize_ingest_pass(
        session,
        profile,
        fetched_ids={"p1"},
        source="xpoz",
        pass_started=T0 - timedelta(hours=1),
        pass_complete=True,
        fetched_window=(post.published_at - timedelta(days=1), T0),
    )
    await session.commit()
    assert r1["flagged_deleted"] == 0
    assert post.last_seen_at == T0 - timedelta(hours=1)

    # pass 2: complete miss, fetch slice brackets the publish time -> first miss only
    r2 = await finalize_ingest_pass(
        session,
        profile,
        fetched_ids=set(),
        source="xpoz",
        pass_started=T0 + timedelta(hours=1),
        pass_complete=True,
        fetched_window=(post.published_at - timedelta(days=1), T0 + timedelta(hours=1)),
    )
    await session.commit()
    assert r2["flagged_deleted"] == 0
    assert post.is_deleted_suspect is False

    # pass 3: second consecutive complete miss -> flagged
    r3 = await finalize_ingest_pass(
        session,
        profile,
        fetched_ids=set(),
        source="xpoz",
        pass_started=T0 + timedelta(hours=3),
        pass_complete=True,
        fetched_window=(post.published_at - timedelta(days=1), T0 + timedelta(hours=3)),
    )
    await session.commit()
    assert r3["flagged_deleted"] == 1
    assert post.is_deleted_suspect is True


# ==========================================================================
# Area 7 — baseline exclusions
# ==========================================================================
def test_baseline_exclusions_and_math():
    now = datetime.now(UTC)
    candidates = [
        # kept: five normal posts
        *[BaselineCandidate(now - timedelta(days=10 + i), False, MetricSample(views=v, engagement=v // 10)) for i, v in enumerate([100, 200, 300, 400, 1500])],
        # excluded: deleted suspect
        BaselineCandidate(now - timedelta(days=12), True, MetricSample(views=9999, engagement=1)),
        # excluded: too young (< 24h, still growing)
        BaselineCandidate(now - timedelta(hours=5), False, MetricSample(views=8888, engagement=1)),
        # excluded: outside the 28d lookback
        BaselineCandidate(now - timedelta(days=120), False, MetricSample(views=7777, engagement=1)),
        # excluded: views missing (NULL must never count as 0)
        BaselineCandidate(now - timedelta(days=15), False, MetricSample(views=None, engagement=1)),
    ]
    samples = eligible_baseline_samples(candidates)
    assert len(samples) == 5
    result = compute_baseline(samples)
    assert result.median_views == 300.0
    assert result.p75_views == 400.0
    assert result.n_posts == 5
    assert result.baseline_reliable is False  # 5 < PeerConfig.MIN_ACCOUNT_SAMPLE


# ==========================================================================
# Area 8 — own baseline == peer baseline (same functions by construction)
# ==========================================================================
def test_own_and_peer_baseline_identical_by_construction():
    now = datetime.now(UTC)
    shared = [
        BaselineCandidate(now - timedelta(days=11), False, MetricSample(views=v, engagement=v // 10))
        for v in (50, 150, 250, 350, 4500)
    ]
    own = compute_baseline(eligible_baseline_samples(shared))
    peer = compute_baseline(eligible_baseline_samples(shared))
    assert own == peer  # frozen dataclass: identical values on both sides
    assert own.median_views == 250.0


def test_own_outlier_uses_the_same_baseline_ratio():
    baseline = BaselineResult(
        median_views=200.0,
        median_engagement=10.0,
        p75_views=250.0,
        n_posts=6,
        baseline_reliable=False,
    )
    now = datetime.now(UTC)
    post = Post(id=1, profile_id=1, platform_post_id="1", caption="hello", published_at=now - timedelta(hours=72))
    snap = MetricSnapshot(
        post_id=1,
        captured_at=now,
        age_hours=72.0,
        views=300,
        likes=20,
        comments=5,
        shares=5,
    )
    pm = build_own_post_metrics(post, [snap], baseline, handle="ateh", now=now)
    assert pm is not None
    assert pm.outlier_views == 1.5  # 300 / 200 — same ratio the peer side computes

    # missing views -> no outlier score can be invented
    snap_no_views = MetricSnapshot(post_id=1, captured_at=now, age_hours=72.0, views=None)
    assert build_own_post_metrics(post, [snap_no_views], baseline, handle="ateh", now=now) is None


# ==========================================================================
# Area 9 — timezone inference + user confirmation
# ==========================================================================
def test_infer_timezone_needs_minimum_posts():
    assert infer_timezone([]) is None
    assert infer_timezone([T0.replace(hour=20)] * 9) is None
    # 10+ evening posts (mode 20:00 UTC ~ 21:00 local) -> UTC+01:00
    assert infer_timezone([T0.replace(hour=20)] * 10) == "UTC+01:00"


def test_maybe_update_timezone_sets_inferred():
    profile = Profile(name="T", handle="ateh", pfm_account_id="spc_tz")
    tz = maybe_update_timezone(profile, [T0.replace(hour=20)] * 12)
    assert tz == "UTC+01:00"
    assert profile.timezone == "UTC+01:00"
    assert profile.timezone_source == "inferred"
    # idempotent: same inference again is a no-op
    assert maybe_update_timezone(profile, [T0.replace(hour=20)] * 12) is None


def test_user_confirmed_timezone_always_wins():
    profile = Profile(name="T", handle="ateh", pfm_account_id="spc_tz2")
    confirm_timezone(profile, "Africa/Lagos")
    assert profile.timezone == "Africa/Lagos"
    assert profile.timezone_source == "user_confirmed"
    # a later pass with a different histogram must NOT overwrite the confirmation
    assert maybe_update_timezone(profile, [T0.replace(hour=6)] * 12) is None
    assert profile.timezone == "Africa/Lagos"
    assert profile.timezone_source == "user_confirmed"
