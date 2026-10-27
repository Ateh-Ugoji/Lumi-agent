"""Blind post tagging for the peer pipeline (Prompt 1 — the `extract` stage).

The LLM sees **text only**: no views, no outlier scores, no winner flags. Code
decides who won (`winners.py`); the model only describes structure, so it cannot
pattern-match "this one performed well". Everything here degrades honestly: a
bad response, a timeout, or a validation error produces `PostTagging` rows with
`status="failed"` and a reason — never an invented analysis.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import neatlogs
from pydantic import ValidationError

from app.agent.providers import chat_completion_with_fallback
from app.schemas.peer import (
    PeerConfig,
    PostAnalysis,
    PostAnalysisBatch,
    PostMetrics,
    PostTagging,
)

log = logging.getLogger(__name__)

TAGGING_PROMPT_VERSION = "peer-tag-v1"

_SYSTEM_PROMPT = f"""You are a meticulous content-structure analyst.

You will receive a batch of social posts as JSON: each has an id and its text.
For EVERY post, describe only its structure — never its performance.

Rules:
- Blind analysis: you are not told which posts performed well; do not guess.
- Use the exact enums; unknown value -> "other".
- "primary_framework" requires its detail block: pas -> "pas", aida -> "aida",
  story_arc -> "story_arc". Others need no detail block.
- "hook_text" must be a verbatim slice of the post (first line/sentence).
- Scores are integers 1-5 (specificity/tension/clarity), confidence is 0-1.
- Return ONLY JSON of the shape {{"analyses": [ ... ]}}, one entry per input id.

Batch size: {PeerConfig.BATCH_SIZE}. Framework confidence below
{PeerConfig.LOW_CONFIDENCE} means you are unsure — say so, do not force it.
"""


def build_tagging_messages(posts: list[PostMetrics]) -> list[dict]:
    """Blind payload: ids + text (+ thread continuation) only."""
    payload = [
        {"post_id": p.post_id, "text": p.text, "thread_texts": p.thread_texts}
        for p in posts
    ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"posts": payload}, ensure_ascii=False)},
    ]


def parse_analyses(content: str | None) -> PostAnalysisBatch:
    """Parse the model's reply into a validated batch (raises on junk)."""
    if not content:
        raise ValueError("empty completion")
    text = content.strip()
    for fence in ("```json", "```JSON", "```"):
        text = text.replace(fence, "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in completion")
    data = json.loads(text[start : end + 1])
    return PostAnalysisBatch(**data)


def _tagging(
    post: PostMetrics,
    *,
    status: str,
    analysis: PostAnalysis | None = None,
    error: str | None = None,
) -> PostTagging:
    guess = None
    if analysis is not None and analysis.body.framework_confidence < PeerConfig.LOW_CONFIDENCE:
        # keep the original guess when the model was unsure (Prompt 1 audit fix)
        guess = analysis.body.primary_framework
    return PostTagging(
        post_id=post.post_id,
        handle=post.handle,
        status=status,  # type: ignore[arg-type]
        analysis=analysis,
        framework_guess=guess,
        validation_error=error,
        prompt_version=TAGGING_PROMPT_VERSION,
        tagged_at=datetime.now(UTC),
    )


def _failed_batch(posts: list[PostMetrics], reason: str) -> list[PostTagging]:
    """Every post gets an honest failed row — no analysis is ever invented."""
    return [_tagging(p, status="failed", error=reason) for p in posts]


@neatlogs.span(kind="CHAIN", name="peer_tag_batch")
async def tag_batch(posts: list[PostMetrics]) -> list[PostTagging]:
    """Tag one batch (<= PeerConfig.BATCH_SIZE posts). Never raises."""
    if not posts:
        return []
    try:
        completion = await chat_completion_with_fallback(build_tagging_messages(posts), [])
    except Exception as exc:  # noqa: BLE001
        log.warning("peer tagging call failed: %s", exc)
        return _failed_batch(posts, f"llm_call_failed: {exc}")

    content = completion.choices[0].message.content if completion.choices else None
    try:
        batch = parse_analyses(content)
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        log.warning("peer tagging unparseable: %s", exc)
        return _failed_batch(posts, f"unparseable_response: {exc}")

    by_id = {a.post_id: a for a in batch.analyses}
    out: list[PostTagging] = []
    for post in posts:
        analysis = by_id.get(post.post_id)
        if analysis is None:
            out.append(_tagging(post, status="failed", error="missing from model response"))
        else:
            out.append(_tagging(post, status="ok", analysis=analysis))
    return out


async def tag_posts(posts: list[PostMetrics]) -> list[PostTagging]:
    """Tag every post in batches of PeerConfig.BATCH_SIZE. Never raises."""
    if not posts:
        return []
    size = PeerConfig.BATCH_SIZE
    taggings: list[PostTagging] = []
    for start in range(0, len(posts), size):
        taggings.extend(await tag_batch(posts[start : start + size]))
    return taggings


def lift_attributes(
    posts: list[PostMetrics], taggings: list[PostTagging]
) -> dict[str, dict[str, str]]:
    """post_id -> dimension attributes for the lift table (code-owned mapping).

    Structure dimensions come from the blind tagging; `format` comes from the
    computed post metrics — the LLM is never asked for performance-adjacent data.
    Untagged / failed posts are simply absent, so they sit out the lift math.
    """
    by_id = {t.post_id: t for t in taggings if t.status == "ok" and t.analysis is not None}
    out: dict[str, dict[str, str]] = {}
    for post in posts:
        tagging = by_id.get(post.post_id)
        if tagging is None or tagging.analysis is None:
            continue
        analysis = tagging.analysis
        out[post.post_id] = {
            "primary_framework": analysis.body.primary_framework,
            "hook_type": analysis.hook.hook_type,
            "format": post.format,
            "cta_type": analysis.cta.cta_type,
            "funnel_stage": analysis.strategy.funnel_stage,
            "content_pillar": analysis.strategy.content_pillar,
            "hook_modality": analysis.hook.modality,
        }
    return out
