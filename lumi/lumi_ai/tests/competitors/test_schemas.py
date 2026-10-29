"""Validation tests for the peer-framework analysis schemas (lumi/legacy/app/schemas/peer.py)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from lumi_ai.competitors.schemas.peer import (
    BodyAnalysis,
    HookAnalysis,
    NicheFrameworkReport,
    PASDetail,
    PeerConfig,
    PostStats,
    PostTagging,
)


def _minimal_post_metrics(**overrides) -> PostStats:
    base = {
        "post_id": "123",
        "handle": "peer",
        "created_at": datetime(2026, 10, 15, 14, 0, tzinfo=UTC),
        "age_hours": 48.0,
        "text": "Shipped X. Here's what broke.",
        "format": "single",
        "views": 10_000,
        "likes": 400,
        "replies": 30,
        "reposts": 25,
        "engagement_total": 455,
        "engagement_rate_views": 0.0455,
        "outlier_views": 2.1,
        "outlier_engagement": 1.8,
        "reply_to_like": 0.075,
        "repost_to_like": 0.0625,
        "bookmark_to_like": 0.02,
        "char_count": 31,
        "line_count": 1,
        "hook_word_count": 4,
        "hashtag_count": 0,
        "has_external_link": False,
        "day_of_week": 2,
        "hour_utc": 14,
    }
    base.update(overrides)
    return PostStats(**base)


def test_post_metrics_accepts_missing_quotes_and_bookmarks():
    m = _minimal_post_metrics(quotes=None, bookmarks=None)
    assert m.quotes is None
    assert m.bookmarks is None


def test_post_metrics_computed_defaults():
    m = _minimal_post_metrics()
    assert m.emoji_count == 0
    assert m.hours_since_prev is None
    assert m.hours_to_next is None
    assert m.is_pinned is False and m.is_boosted_suspect is False


def test_post_metrics_rejects_out_of_range_timing():
    with pytest.raises(ValidationError):
        _minimal_post_metrics(hour_utc=24)
    with pytest.raises(ValidationError):
        _minimal_post_metrics(day_of_week=7)


def _pas_detail() -> PASDetail:
    return PASDetail(
        problem_text="you ship slow",
        pain_type="time",
        agitation_steps=1,
        mechanism_present=True,
        char_split_p=0.4,
        char_split_a=0.2,
        char_split_s=0.4,
    )


def test_body_analysis_requires_detail_block_for_primary_framework():
    common = {
        "framework_confidence": 0.8,
        "specificity_score": 4,
        "open_loops": 0,
        "line_break_style": "one_liners",
    }
    with pytest.raises(ValidationError):
        BodyAnalysis(primary_framework="pas", pas=None, **common)
    ok = BodyAnalysis(primary_framework="pas", pas=_pas_detail(), **common)
    assert ok.pas is not None


def test_body_analysis_no_detail_required_for_other_frameworks():
    ok = BodyAnalysis(
        primary_framework="hot_take",
        framework_confidence=0.9,
        specificity_score=3,
        open_loops=0,
        line_break_style="short_paragraphs",
    )
    assert ok.pas is None and ok.aida is None and ok.story_arc is None


def test_hook_analysis_score_bounds():
    with pytest.raises(ValidationError):
        HookAnalysis(
            hook_text="x",
            hook_type="contrarian",
            modality="text_only",
            has_number=False,
            has_named_entity=False,
            open_loop=False,
            specificity=6,  # out of 1-5
            tension=3,
            clarity=3,
            confidence=0.5,
        )


def test_post_tagging_default_status_is_pending():
    t = PostTagging(post_id="1", handle="peer")
    assert t.status == "pending"
    assert t.analysis is None


def test_config_carries_report_floor():
    assert PeerConfig.MIN_WINNERS_FOR_REPORT == 8
    assert PeerConfig.MIN_OUTLIER_FOR_WINNER == 1.5
    assert PeerConfig.MAX_WINNERS_PER_ACCOUNT <= PeerConfig.TOP_N_WINNERS


def test_failed_report_constructs_without_fabricated_frameworks():
    """Ported from legacy test_niche_schemas (failed NicheProfile): a failure invents nothing."""
    report = NicheFrameworkReport(
        niche="ai:global",
        generated_at=datetime(2026, 10, 17, 12, 0, tzinfo=UTC),
        status="failed",
        accounts=[],
        winner_post_ids=[],
        posts_analyzed=0,
        lift_table=[],
    )
    assert report.status == "failed"
    assert report.synthesis is None and report.trend_delta is None
    assert report.winner_post_ids == [] and report.lift_table == []
