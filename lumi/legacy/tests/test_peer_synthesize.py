"""Tests for the peer pipeline's synthesis (Prompt 1 — synthesize stage).

Locks the grounding rule: every framework, pillar and whitespace entry traces
back to a *reported* lift row, and a report that cannot be supported carries no
synthesis at all rather than invented frameworks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.analysis.synthesize import (
    STRUCTURE_BY_FRAMEWORK,
    build_report,
    build_synthesis,
)
from app.analysis.winners import (
    ScrapedPost,
    WinnerSelection,
    build_account_baseline,
    build_post_metrics,
)
from app.schemas.peer import LiftRow, PostAnalysis, PostMetrics, PostTagging

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _row(
    dimension: str,
    value: str,
    lift: float | None,
    *,
    n_winners: int = 4,
    n_baseline: int = 4,
    status: str = "reported",
    baseline_share: float = 0.4,
) -> LiftRow:
    return LiftRow(
        dimension=dimension,  # type: ignore[arg-type]
        value=value,
        n_winners=n_winners,
        n_baseline=n_baseline,
        winner_share=0.5,
        baseline_share=baseline_share,
        lift=lift,
        status=status,  # type: ignore[arg-type]
    )


def _analysis(post_id: str, framework: str, confidence: float, hook_type: str) -> PostAnalysis:
    return PostAnalysis(
        post_id=post_id,
        hook={
            "hook_text": "first line",
            "hook_type": hook_type,
            "modality": "text_only",
            "has_number": False,
            "has_named_entity": False,
            "open_loop": False,
            "specificity": 3,
            "tension": 3,
            "clarity": 3,
            "confidence": 0.9,
        },
        body={
            "primary_framework": framework,
            "framework_confidence": confidence,
            "specificity_score": 3,
            "open_loops": 0,
            "line_break_style": "short_paragraphs",
        },
        cta={"cta_type": "none", "placement": "none", "friction": "low"},
        voice={"pov": "first_person", "tone": ["direct"], "formality": 3, "humor": 0},
        strategy={
            "content_pillar": "build in public",
            "angle": "shipping",
            "intent": "educate",
            "funnel_stage": "awareness",
        },
    )


def _tagging(post_id: str, framework: str, confidence: float, *, status: str = "ok") -> PostTagging:
    return PostTagging(
        post_id=post_id,
        handle="a",
        status=status,  # type: ignore[arg-type]
        analysis=None if status != "ok" else _analysis(post_id, framework, confidence, "curiosity_gap"),
        prompt_version="peer-tag-v1",
        tagged_at=NOW,
    )


def _metrics(post_id: str) -> PostMetrics:
    scraped = ScrapedPost(
        post_id=post_id,
        handle="a",
        created_at=NOW - timedelta(hours=48),
        text="first line\nsecond",
        views=3000,
        likes=10,
    )
    baseline = build_account_baseline("a", [scraped], now=NOW)
    metrics = build_post_metrics(scraped, baseline, now=NOW)
    assert metrics is not None
    return metrics


def _selection(status: str = "ok", winner_ids: tuple[str, ...] = ("w1",)) -> WinnerSelection:
    return WinnerSelection(
        status=status,  # type: ignore[arg-type]
        winners=[_metrics(pid) for pid in winner_ids],
        baselines={},
    )


# ---------------------------------------------------------------- synthesis
def test_framework_is_reported_only_when_it_lifts() -> None:
    rows = [
        _row("primary_framework", "hot_take", 2.0),
        _row("hook_type", "curiosity_gap", 1.2),
    ]
    taggings = [
        _tagging("w1", "hot_take", 0.8),
        _tagging("w2", "hot_take", 0.9),
        _tagging("w3", "hot_take", 1.0),
        _tagging("b1", "observation", 0.9),
    ]
    synthesis = build_synthesis(rows, taggings, ["w1", "w2", "w3"])

    assert len(synthesis.winning_frameworks) == 1
    framework = synthesis.winning_frameworks[0]
    assert framework.name == "Hot Take"
    assert framework.structure == STRUCTURE_BY_FRAMEWORK["hot_take"]
    assert sorted(framework.evidence_post_ids) == ["w1", "w2", "w3"]
    assert framework.confidence == 0.9  # mean of the winner taggings
    assert "primary_framework=hot_take" in framework.supporting_lift_rows
    assert "hook_type=curiosity_gap" in framework.supporting_lift_rows
    assert synthesis.warnings == []


def test_low_lift_yields_no_frameworks_and_a_warning() -> None:
    rows = [_row("primary_framework", "hot_take", 1.1)]
    synthesis = build_synthesis(rows, [_tagging("w1", "hot_take", 0.9)], ["w1"])
    assert synthesis.winning_frameworks == []
    assert any("no framework pattern lifted" in w for w in synthesis.warnings)


def test_insufficient_rows_are_never_reported_regardless_of_lift() -> None:
    rows = [_row("primary_framework", "hot_take", 9.0, status="insufficient_data")]
    synthesis = build_synthesis(rows, [_tagging("w1", "hot_take", 0.9)], ["w1"])
    assert synthesis.winning_frameworks == []


def test_unsupported_winner_taggings_contribute_nothing() -> None:
    rows = [_row("primary_framework", "hot_take", 2.0)]
    # the analysis belongs to a post that is not a winner -> no evidence to cite
    synthesis = build_synthesis(rows, [_tagging("b1", "hot_take", 0.9)], ["w1"])
    assert synthesis.winning_frameworks[0].evidence_post_ids == []
    assert synthesis.winning_frameworks[0].confidence == 0.6  # LOW_CONFIDENCE fallback


def test_pillars_and_whitespace_come_from_reported_rows() -> None:
    rows = [
        _row("content_pillar", "build in public", 2.0),
        _row("content_pillar", "opinions", 0.6),
        _row("hook_type", "stat_shock", 3.0, baseline_share=0.1),
        _row("hook_type", "question", 2.0, baseline_share=0.5),  # common among peers -> not whitespace
    ]
    synthesis = build_synthesis(rows, [_tagging("w1", "hot_take", 0.9)], ["w1"])
    assert synthesis.content_pillars == ["build in public"]
    assert synthesis.whitespace == ["hook_type=stat_shock"]


# ---------------------------------------------------------------- report
def test_report_is_insufficient_data_without_synthesis() -> None:
    report = build_report(
        niche="nigerian tech",
        accounts=[],
        selection=_selection(status="insufficient_data"),
        taggings=[_tagging("w1", "hot_take", 0.9)],
        lift_rows=[_row("primary_framework", "hot_take", 2.0)],
        now=NOW,
    )
    assert report.status == "insufficient_data"
    assert report.synthesis is None
    # the few winners that were found are still recorded honestly — only the
    # frameworks (which need the full floor) are withheld
    assert report.winner_post_ids == ["w1"]


def test_failed_tagging_yields_a_failed_report_with_no_frameworks() -> None:
    report = build_report(
        niche="nigerian tech",
        accounts=[],
        selection=_selection(status="ok", winner_ids=("w1", "w2")),
        taggings=[_tagging("w1", "hot_take", 0.9, status="failed")],
        lift_rows=[_row("primary_framework", "hot_take", 2.0)],
        now=NOW,
    )
    assert report.status == "failed"
    assert report.synthesis is None
    assert report.posts_analyzed == 0


def test_supported_report_carries_synthesis_and_counts() -> None:
    report = build_report(
        niche="nigerian tech",
        accounts=[],
        selection=_selection(status="ok", winner_ids=("w1", "w2")),
        taggings=[_tagging("w1", "hot_take", 0.9), _tagging("w2", "hot_take", 0.8)],
        lift_rows=[_row("primary_framework", "hot_take", 2.0)],
        now=NOW,
    )
    assert report.status == "ok"
    assert report.synthesis is not None
    assert len(report.synthesis.winning_frameworks) == 1
    assert report.posts_analyzed == 2
    assert report.generated_at == NOW
