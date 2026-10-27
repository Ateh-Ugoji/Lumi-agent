from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.connections.ingest import (
    PostFlags,
    classify_post,
    classify_post_kind,
    detect_truncation,
    is_authentic_original,
    map_pfm_item,
    map_xpoz_post,
    parse_datetime,
    pfm_metrics,
    routes_to_activity,
)

from .fakes import fixture


def test_classify_post_kind() -> None:
    assert classify_post_kind("@tsola_ps 😂😂") == "reply"
    assert classify_post_kind("RT @someone: great thread") == "retweet"
    assert classify_post_kind("rt: old-style marker") == "retweet"
    assert classify_post_kind("Don't run out of money.") == "original"
    assert classify_post_kind("“my take” — quote keeps own words") == "original"


def test_rt_variants_are_rejected() -> None:
    for text in (
        "RT @someone: great thread on agents",
        "rt @someone: lower-case prefix",
        "RT: just an old-style retweet marker",
        "RT someone forgot the at-sign",
    ):
        assert not is_authentic_original(text)


def test_replies_and_mention_openers_are_rejected() -> None:
    for text in (
        "@tsola_ps 😂😂",
        "@lou3ee Just sent a DM 💙",
        "  @leading_space still a reply",
        "@",
    ):
        assert not is_authentic_original(text)


def test_original_posts_and_quotes_are_kept() -> None:
    assert is_authentic_original("Don't run out of money. That's the whole job.")
    assert is_authentic_original("Great to catch up, @Shalom_heyeliy! Dream bigger.")
    assert is_authentic_original(
        "Everyone: 'Got accepted in 2mins'. Me: https://t.co/abc"
    )
    assert is_authentic_original(
        "“Shirt by Chizi” — my take on event fashion https://t.co/xyz"
    )


@pytest.mark.parametrize("text", ["", None, "   "])
def test_empty_and_whitespace_are_rejected(text) -> None:
    assert not is_authentic_original(text)


def test_replies_and_retweets_route_to_activity() -> None:
    assert routes_to_activity("reply") and routes_to_activity("retweet")
    assert not routes_to_activity("original") and not routes_to_activity("quote")
    assert not routes_to_activity(None)


def test_api_flags_beat_text_heuristics() -> None:
    flags = PostFlags(
        reply_to_tweet_id="1", reply_to_username="friend", conversation_id="1"
    )
    assert (
        classify_post("Looks original", flags=flags, user_handle="ateh").kind == "reply"
    )
    assert (
        classify_post(
            "@friend looks like a reply", flags=PostFlags(conversation_id="9")
        ).kind
        == "original"
    )
    assert classify_post("x", flags=PostFlags(is_retweet=True)).kind == "retweet"
    assert classify_post("x", flags=PostFlags(quoted_tweet_id="5")).kind == "quote"


def test_self_reply_is_a_thread_continuation_not_a_reply() -> None:
    flags = PostFlags(
        reply_to_tweet_id="1", reply_to_username="@Ateh", conversation_id="1"
    )
    verdict = classify_post("part two", flags=flags, user_handle="ateh")
    assert (verdict.kind, verdict.kind_source, verdict.conversation_id) == (
        "original",
        "api",
        "1",
    )


def test_no_flags_falls_back_to_the_heuristic() -> None:
    verdict = classify_post("RT @x: y", flags=PostFlags())
    assert (verdict.kind, verdict.kind_source) == ("retweet", "heuristic")


def test_truncation_needs_the_near_limit_length() -> None:
    assert detect_truncation("a" * 274 + "...")
    assert detect_truncation("a" * 250 + " https://t.co/abc12345")
    assert not detect_truncation("short...")
    assert not detect_truncation("a" * 400 + "...")
    assert not detect_truncation(None)


def test_parse_datetime_is_always_aware_and_never_invented() -> None:
    assert parse_datetime("2026-10-20T10:00:00Z") == datetime(
        2026, 10, 20, 10, tzinfo=UTC
    )
    assert parse_datetime("2026-10-20T10:00:00").tzinfo is not None
    assert parse_datetime("not a date") is None and parse_datetime(None) is None


def test_x_metrics_come_from_public_metrics_and_zero_stays_zero() -> None:
    m = pfm_metrics(
        "x",
        {
            "public_metrics": {
                "like_count": 0,
                "impression_count": 900,
                "reply_count": 3,
            }
        },
    )
    assert (m.likes, m.views, m.comments) == (0, 900, 3)
    assert m.shares is None and m.bookmarks is None and m.quotes is None


def test_x_views_fall_back_to_organic_metrics() -> None:
    m = pfm_metrics(
        "x",
        {
            "public_metrics": {"like_count": 1},
            "organic_metrics": {"impression_count": 77},
        },
    )
    assert m.views == 77


@pytest.mark.parametrize(
    "platform", ["x", "instagram", "tiktok", "facebook", "linkedin", "youtube"]
)
@pytest.mark.parametrize("metrics", [None, {}, "nope", []])
def test_missing_metrics_are_none_never_zero(platform: str, metrics) -> None:
    m = pfm_metrics(platform, metrics)
    assert (m.views, m.likes, m.comments, m.shares, m.bookmarks, m.quotes) == (
        None,
    ) * 6


def test_other_platform_metric_shapes() -> None:
    ig = pfm_metrics(
        "instagram",
        {"likes": 50, "comments": 4, "views": 1200, "saved": 9, "shares": 3},
    )
    assert (ig.likes, ig.views, ig.bookmarks, ig.shares) == (50, 1200, 9, 3)
    tt = pfm_metrics(
        "tiktok",
        {"view_count": 10, "like_count": 2, "comment_count": 1, "share_count": 0},
    )
    assert (tt.views, tt.shares) == (10, 0)
    fb = pfm_metrics("facebook", {"media_views": 5, "reactions_total": 6})
    assert (fb.views, fb.likes) == (5, 6)
    li = pfm_metrics("linkedin", {"impressionCount": 8, "likeCount": 1})
    assert (li.views, li.likes) == (8, 1)


def test_map_pfm_item_from_the_recorded_page() -> None:
    items = fixture("pfm_feed_x_page1.json")["data"]
    mapped = [map_pfm_item(i, handle="@Ateh") for i in items]
    first, reply, bare = mapped
    assert (
        first.platform == "x" and first.external_id == "101" and first.source == "pfm"
    )
    assert first.author_handle == "ateh" and first.kind == "original"
    assert first.metrics.views == 900 and first.metrics.bookmarks == 4
    assert first.url == "https://x.com/ateh/status/101"
    assert reply.kind == "reply"
    assert bare.metrics.views is None and bare.metrics.likes is None


def test_map_pfm_item_drops_unusable_items() -> None:
    base = fixture("pfm_feed_x_page1.json")["data"][0]
    assert map_pfm_item({**base, "platform": "youtube"}) is None
    assert map_pfm_item({**base, "platform_post_id": None}) is None
    assert map_pfm_item({**base, "caption": "  "}) is None
    assert map_pfm_item({**base, "posted_at": "garbage"}) is None
    assert map_pfm_item({**base, "posted_at": None}) is None


def test_map_xpoz_post_uses_structural_flags() -> None:
    rows = (
        fixture("xpoz_user_posts_page1.json")["results"]
        + fixture("xpoz_user_posts_page2.json")["results"]
    )
    by_id = {
        p.external_id: p for r in rows if (p := map_xpoz_post(r, user_handle="ateh"))
    }
    assert by_id["201"].kind == "original"
    assert by_id["200"].kind == "reply"
    assert by_id["199"].kind == "original" and by_id["199"].conversation_id == "198"
    assert by_id["197"].kind == "quote"
    p = by_id["201"]
    assert p.source == "xpoz" and p.platform == "x" and p.language == "en"
    assert (p.metrics.views, p.metrics.likes, p.metrics.shares, p.metrics.comments) == (
        500,
        10,
        2,
        1,
    )
    assert p.url == "https://x.com/ateh/status/201"


def test_map_xpoz_post_missing_counts_are_none() -> None:
    row = {
        "id": 5,
        "text": "hi",
        "createdAt": "2026-10-20T10:00:00Z",
        "authorUsername": "A",
    }
    p = map_xpoz_post(row)
    assert p.external_id == "5" and p.author_handle == "a"
    assert p.metrics.likes is None and p.metrics.views is None
    assert map_xpoz_post({"text": "x", "createdAt": "2026-10-20T10:00:00Z"}) is None
    assert map_xpoz_post({"id": 1, "text": "x", "createdAt": "bad"}) is None


def test_media_is_never_invented() -> None:
    item = {
        **fixture("pfm_feed_x_page1.json")["data"][0],
        "media": [{"url": "https://img.example/a.jpg"}],
    }
    assert map_pfm_item(item).media == ()


def test_pfm_media_keeps_only_entries_with_a_stated_kind() -> None:
    from lumi_ai.ports import MediaRef

    item = {
        **fixture("pfm_feed_x_page1.json")["data"][0],
        "media": [
            {"url": "https://img.example/a.jpg", "type": "image"},
            {"media_url": "https://v.example/b.mp4", "mime_type": "video/mp4"},
            {"url": "https://img.example/c.gif", "kind": "image/gif"},
            {"url": "https://img.example/d.jpg", "type": "hologram"},
            {"url": "ftp://img.example/e.jpg", "type": "image"},
            {"type": "image"},
            "https://img.example/f.jpg",
        ],
    }
    assert map_pfm_item(item).media == (
        MediaRef("image", "https://img.example/a.jpg"),
        MediaRef("video", "https://v.example/b.mp4"),
        MediaRef("gif", "https://img.example/c.gif"),
    )
    assert map_pfm_item({**item, "media": "nope"}).media == ()


def test_xpoz_x_media_is_not_mapped_until_persistence_accepts_unknown_kind() -> None:
    post = map_xpoz_post(
        {
            "id": 7,
            "text": "hi",
            "createdAt": "2026-10-20T10:00:00Z",
            "mediaUrls": ["https://pbs.example/a.jpg"],
        }
    )
    assert post.media == ()
