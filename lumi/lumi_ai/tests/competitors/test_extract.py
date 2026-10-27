"""Tests for the peer pipeline's blind tagging (Prompt 1 — extract stage).

The LLM is a scripted fake; what is locked here is the contract: blind payloads,
validated parsing, and honest failure rows that never carry an invented analysis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from lumi_ai.competitors.extract import (
    TAGGING_PROMPT_VERSION,
    build_tagging_messages,
    lift_attributes,
    parse_analyses,
    tag_posts,
)
from lumi_ai.competitors.schemas.peer import PeerConfig, PostStats
from lumi_ai.competitors.winners import (
    ScrapedPost,
    build_account_baseline,
    build_post_metrics,
)
from lumi_ai.tests.agent.harness import FakeLLM, say

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _post(post_id: str, handle: str = "a") -> PostStats:
    scraped = ScrapedPost(
        post_id=post_id,
        handle=handle,
        created_at=NOW - timedelta(hours=48),
        text=f"first line of {post_id}\nsecond line",
        views=3000,
        likes=20,
        replies=3,
        reposts=2,
    )
    baseline = build_account_baseline(handle, [scraped], now=NOW)
    metrics = build_post_metrics(scraped, baseline, now=NOW)
    assert metrics is not None
    return metrics


def _analysis_json(
    post_id: str, framework: str = "hot_take", confidence: float = 0.9
) -> dict:
    body: dict = {
        "primary_framework": framework,
        "framework_confidence": confidence,
        "specificity_score": 3,
        "open_loops": 1,
        "line_break_style": "short_paragraphs",
    }
    if framework == "pas":
        body["pas"] = {
            "problem_text": "P",
            "pain_type": "time",
            "agitation_steps": 1,
            "mechanism_present": True,
            "char_split_p": 0.4,
            "char_split_a": 0.3,
            "char_split_s": 0.3,
        }
    return {
        "post_id": post_id,
        "hook": {
            "hook_text": "first line",
            "hook_type": "curiosity_gap",
            "modality": "text_only",
            "has_number": False,
            "has_named_entity": False,
            "open_loop": True,
            "specificity": 3,
            "tension": 3,
            "clarity": 4,
            "confidence": 0.9,
        },
        "body": body,
        "cta": {
            "cta_type": "reply_keyword",
            "placement": "last_line",
            "friction": "low",
        },
        "voice": {"pov": "first_person", "tone": ["blunt"], "formality": 3, "humor": 1},
        "strategy": {
            "content_pillar": "build in public",
            "angle": "shipping",
            "intent": "educate",
            "funnel_stage": "awareness",
        },
    }


def _payload(*analyses: dict) -> str:
    return json.dumps({"analyses": list(analyses)})


# ---------------------------------------------------------------- parsing
def test_parse_accepts_fenced_json_and_validates() -> None:
    batch = parse_analyses("```json\n" + _payload(_analysis_json("p1")) + "\n```")
    assert [a.post_id for a in batch.analyses] == ["p1"]


@pytest.mark.parametrize(
    "content", [None, "", "no json here", '{"analyses": [{"post_id": "p1"}]}']
)
def test_parse_rejects_junk(content: str | None) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_analyses(content)


# ---------------------------------------------------------------- tagging
async def test_valid_batch_is_tagged_ok() -> None:
    posts = [_post("p1"), _post("p2")]
    llm = FakeLLM([say(_payload(_analysis_json("p1"), _analysis_json("p2")))])
    taggings = await tag_posts(llm, posts)
    assert [t.status for t in taggings] == ["ok", "ok"]
    assert all(t.prompt_version == TAGGING_PROMPT_VERSION for t in taggings)
    assert all(t.analysis is not None for t in taggings)
    assert all(t.framework_guess is None for t in taggings)  # 0.9 >= LOW_CONFIDENCE


async def test_low_confidence_keeps_the_original_framework_guess() -> None:
    llm = FakeLLM([say(_payload(_analysis_json("p1", confidence=0.4)))])
    tagging = (await tag_posts(llm, [_post("p1")]))[0]
    assert tagging.status == "ok"
    assert tagging.framework_guess == "hot_take"


async def test_unparseable_response_never_invents_an_analysis() -> None:
    posts = [_post("p1"), _post("p2")]
    taggings = await tag_posts(FakeLLM([say("sure! great posts")]), posts)
    assert {t.status for t in taggings} == {"failed"}
    assert all(t.analysis is None for t in taggings)
    assert all(
        (t.validation_error or "").startswith("unparseable_response") for t in taggings
    )


async def test_llm_failure_is_honest() -> None:
    class Broken:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("all LLM providers failed")

    tagging = (await tag_posts(Broken(), [_post("p1")]))[0]
    assert tagging.status == "failed"
    assert tagging.analysis is None
    assert "llm_call_failed" in (tagging.validation_error or "")


async def test_post_missing_from_response_fails_only_that_post() -> None:
    posts = [_post("p1"), _post("p2")]
    taggings = await tag_posts(FakeLLM([say(_payload(_analysis_json("p1")))]), posts)
    assert [(t.post_id, t.status) for t in taggings] == [("p1", "ok"), ("p2", "failed")]


async def test_batches_are_chunked_at_batch_size() -> None:
    posts = [_post(f"p{i}") for i in range(PeerConfig.BATCH_SIZE + 1)]
    payload = _payload(*[_analysis_json(p.post_id) for p in posts])
    llm = FakeLLM([say(payload), say(payload)])
    await tag_posts(llm, posts)
    assert len(llm.seen) == 2
    assert llm.script == []


# ---------------------------------------------------------------- blindness
def test_payload_carries_no_performance_data() -> None:
    blob = json.dumps(build_tagging_messages([_post("p1")])).lower()
    for leaked in ("views", "outlier", "likes", "winner", "engagement"):
        assert leaked not in blob, f"blind payload leaked {leaked}"


async def test_lift_attributes_mix_tagged_structure_with_computed_format() -> None:
    posts = [_post("p1")]
    taggings = await tag_posts(FakeLLM([say(_payload(_analysis_json("p1")))]), posts)
    attrs = lift_attributes(posts, taggings)
    assert attrs["p1"]["primary_framework"] == "hot_take"
    assert attrs["p1"]["format"] == posts[0].format
    assert "views" not in attrs["p1"]
