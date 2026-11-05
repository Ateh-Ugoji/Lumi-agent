"""Agent tools that write posts: ``generate_post`` from a topic and ``repurpose_caption`` from a caption.

Both save a request with every attempt (so the user can accept, edit or reject through
``submit_action``) and answer with the chosen draft plus everything the user needs to judge it:
the checks it passed, the judge's verdict or its absence, the model that wrote it and what the
writer was given. They are registered through ``build_registry(..., extra=build(...))``, so
they exist only when their services do.
"""

from __future__ import annotations

import json
from typing import Any

from lumi_ai.generation.flow import (
    GenerationFailed,
    GenerationResult,
    GenerationService,
)
from lumi_ai.generation.platforms import PLATFORMS, UnknownPlatform, measure, rules_for
from lumi_ai.generation.types import GenerationBrief
from lumi_ai.ports import PostStore
from lumi_ai.tools.registry import ToolContext, ToolSpec

MAX_SOURCE_CHARS = (
    4000  # about 1,000 tokens: the prompt must fit Groq's ~7,000-token wall
)
MAX_PHRASES = 10
MAX_PHRASE_CHARS = 200
_PLATFORM = {
    "type": "string",
    "enum": list(PLATFORMS),
    "description": "Network to write for.",
}
_MUST_KEEP = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Phrases that must appear verbatim in the post (names, offers, slogans).",
}


def normalize_phrases(value: Any) -> list[str]:
    """Phrases as a clean list. Models often pass a JSON string where a list was asked for."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [value]
    if isinstance(value, str) or not isinstance(value, list):
        value = [value]
    seen: dict[str, None] = {}
    for item in value:
        phrase = str(item).strip()
        if phrase:
            seen[phrase] = None
    return list(seen)


def _check_phrases(phrases: list[str]) -> str | None:
    if len(phrases) > MAX_PHRASES:
        return f"at most {MAX_PHRASES} must_keep phrases, got {len(phrases)}"
    long = [p for p in phrases if len(p) > MAX_PHRASE_CHARS]
    if long:
        return f"a must_keep phrase is longer than {MAX_PHRASE_CHARS} characters"
    return None


def _view(result: GenerationResult) -> dict[str, Any]:
    outcome, draft, review = result.outcome, result.draft, result.review
    rules = rules_for(outcome.brief.platform)
    notes = list(review.failures)
    if review.feedback and review.feedback not in notes:
        notes.append(review.feedback)
    if review.needs_retry and not review.failures:
        notes.append(review.revision_note)
    ev = review.evaluation
    judge: dict[str, Any] | None = None
    if review.judge_verdict is not None:
        judge = {"verdict": review.judge_verdict, "confidence": review.judge_confidence}
    view: dict[str, Any] = {
        "request_id": result.request_id,
        "attempt_id": result.attempt.id,
        "platform": outcome.brief.platform,
        "text": draft.text,
        "characters": measure(outcome.brief.platform, draft.text),
        "limit": rules.hard_limit,
        "limit_is_official": rules.limit_is_official,
        "changes": [{"change": c.change, "reason": c.reason} for c in draft.changes],
        "must_keep_passed": review.must_keep_passed,
        "judge": judge,
        "needs_review": (
            review.needs_retry
            or review.judge_source == "none"
            or (ev is not None and ev.judge == "rules")
        ),
        "evaluation": None
        if ev is None
        else {
            "decision": ev.decision,
            "judge": ev.judge,
            "scores": dict(ev.scores),
            "reasons": dict(ev.reasons),
            "style_similarity": ev.style_similarity,
        },
        "notes": [*notes, *result.warnings],
        "model": draft.model,
        "provider": draft.provider,
        "tier": draft.tier,
        "fallback_model_used": draft.is_fallback,
        "attempts_made": len(outcome.attempts),
        "route": outcome.route_label,
        "context_used": {
            "voice": outcome.context.voice,
            "voice_version": outcome.context.voice_version,
            "example_post_ids": list(outcome.context.example_post_ids),
            "frameworks": list(outcome.context.frameworks),
            "warnings": list(outcome.context.warnings),
        },
    }
    return view


def build(service: GenerationService, posts: PostStore | None = None) -> list[ToolSpec]:
    async def generate_post(
        ctx: ToolContext,
        platform: str,
        topic: str,
        goal: str | None = None,
        source: str | None = None,
        must_keep_phrases: Any = None,
    ) -> dict[str, Any]:
        try:
            rules_for(platform)
        except UnknownPlatform as exc:
            return {"error": str(exc)}
        if not (topic or "").strip():
            return {"error": "topic is required"}
        reference = (source or "").strip() or None
        if reference and len(reference) > MAX_SOURCE_CHARS:
            return {
                "error": f"source is longer than {MAX_SOURCE_CHARS} characters; send the relevant part"
            }
        phrases = normalize_phrases(must_keep_phrases)
        if problem := _check_phrases(phrases):
            return {"error": problem}
        brief = GenerationBrief(
            profile_id=ctx.profile_id,
            platform=platform.lower().strip(),  # type: ignore[arg-type]
            mode="topic",
            source_text=reference,
            topic=topic.strip(),
            goal=(goal or "").strip() or None,
            must_keep=tuple(phrases),
        )
        return await _run(service, brief, ctx)

    async def repurpose_caption(
        ctx: ToolContext,
        platform: str,
        post_id: int | None = None,
        source_text: str | None = None,
        must_keep_phrases: Any = None,
    ) -> dict[str, Any]:
        try:
            rules_for(platform)
        except UnknownPlatform as exc:
            return {"error": str(exc)}
        text = (source_text or "").strip()
        if post_id is not None:
            if posts is None:
                return {
                    "error": "reading a stored post is not available; paste the caption as source_text"
                }
            found = [
                p
                for p in await posts.get_posts([post_id])
                if p.profile_id == ctx.profile_id
            ]
            if not found:
                return {"error": f"no post with id {post_id} for this profile"}
            text = found[0].text.strip()
        if not text:
            return {"error": "give post_id or source_text: there is nothing to rewrite"}
        if len(text) > MAX_SOURCE_CHARS:
            return {
                "error": f"the caption is longer than {MAX_SOURCE_CHARS} characters; send the part to rewrite"
            }
        phrases = normalize_phrases(must_keep_phrases)
        if problem := _check_phrases(phrases):
            return {"error": problem}
        brief = GenerationBrief(
            profile_id=ctx.profile_id,
            platform=platform.lower().strip(),  # type: ignore[arg-type]
            mode="repurpose",
            source_text=text,
            must_keep=tuple(phrases),
            source_post_id=post_id,
        )
        return await _run(service, brief, ctx)

    return [
        ToolSpec(
            name="generate_post",
            description=(
                "Write a post for one network from a topic, in the user's own voice, using their own "
                "similar posts and the winning structures of their niche when they exist. Saves every "
                "attempt; answer with the text, the checks it passed and attempt_id for submit_action."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": _PLATFORM,
                    "topic": {
                        "type": "string",
                        "description": "What the post is about.",
                    },
                    "goal": {
                        "type": "string",
                        "description": "What the post should achieve (optional).",
                    },
                    "source": {
                        "type": "string",
                        "description": "Facts or notes to draw from. The post may use only what they say (optional).",
                    },
                    "must_keep_phrases": _MUST_KEEP,
                },
                "required": ["platform", "topic"],
            },
            handler=generate_post,
            cost="llm",
            side_effects="writes_db",
            cache_ttl=0,
        ),
        ToolSpec(
            name="repurpose_caption",
            description=(
                "Rewrite an existing caption or stored post for another network in the user's voice, "
                "keeping its meaning, links and @mentions. Saves every attempt; answer with the text, "
                "the checks it passed and attempt_id for submit_action."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": _PLATFORM,
                    "post_id": {
                        "type": "integer",
                        "description": "A stored post of the user to rewrite.",
                    },
                    "source_text": {
                        "type": "string",
                        "description": "The caption to rewrite, when it is not a stored post.",
                    },
                    "must_keep_phrases": _MUST_KEEP,
                },
                "required": ["platform"],
            },
            handler=repurpose_caption,
            cost="llm",
            side_effects="writes_db",
            cache_ttl=0,
        ),
    ]


async def _run(
    service: GenerationService, brief: GenerationBrief, ctx: ToolContext
) -> dict[str, Any]:
    try:
        result = await service.run(brief, ctx.config)
    except GenerationFailed as exc:
        return {"error": str(exc), "saved": False}
    return _view(result)
