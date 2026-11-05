"""Shared repurpose pipeline: classify -> generate -> enforce -> retry.

Deliberately DB-free so two callers can run it:
- the `repurpose_caption` agent tool (persists one request + attempts), and
- the `POST /repurpose` REST endpoint, which fans out across platforms
  concurrently WITHOUT holding database sessions across LLM calls.

The loop and return shape mirror the original tool implementation exactly
(attempt 1 at the routed tier, one judged retry with feedback on failure);
`tests/test_repurpose_endpoint.py` locks both paths.
"""

import logging
from dataclasses import dataclass

import neatlogs

from app.models.voice import VoiceProfile
from app.services.enforcement import (
    enforce,
    needs_retry,
    platform_char_limit,
    retry_feedback,
)
from app.services.repurpose import (
    ROUTE_TIERS,
    classify_difficulty,
    generate_platform_repurpose,
)

log = logging.getLogger(__name__)


@dataclass
class AttemptRecord:
    """One generation attempt, shaped for `RepurposeAttempt` persistence."""

    attempt_no: int
    platform: str
    tier: str | None
    model: str | None
    provider: str | None
    output: str
    must_keep_passed: bool
    judge_verdict: str | None
    judge_confidence: float | None


@dataclass
class RepurposeOutcome:
    """Everything one platform's pipeline produced — no DB ids attached."""

    platform: str
    route_label: str
    attempts: list[AttemptRecord]
    output: str
    changes: list[dict]
    must_keep_passed: bool
    feedback: str | None
    judge_verdict: str | None
    judge_confidence: float | None
    tier: str | None
    model: str | None

    @property
    def fell_back(self) -> bool:
        """True when the generator silently returned the source unchanged.

        Surfaced by the endpoint as `fallback: true` so clients never present
        a passthrough as a generated recaption (the known repurpose.py smell).
        """
        return any(c.get("reason") == "Fallback mode" for c in self.changes)


@neatlogs.span(kind="CHAIN", name="run_platform_repurpose")
async def run_platform_repurpose(
    source_text: str,
    platform: str,
    voice_profile: VoiceProfile | None = None,
    must_keep_phrases: list[str] | None = None,
    route_label: str | None = None,
) -> RepurposeOutcome:
    """Run the full repurpose pipeline for ONE platform. Pure: no session, no commits."""
    must_keep_phrases = must_keep_phrases or []
    if route_label is None:
        route_label = await classify_difficulty(source_text, platform, must_keep_phrases)
    base_tier = ROUTE_TIERS[route_label]

    attempts: list[AttemptRecord] = []
    repurpose_res: dict = {}
    result = None
    feedback = ""
    for attempt_no in (1, 2):
        repurpose_res = await generate_platform_repurpose(
            source_text=source_text,
            platform=platform,
            voice_profile=voice_profile,
            must_keep_phrases=must_keep_phrases,
            tier=base_tier if attempt_no == 1 else "large",
            revision_feedback=feedback or None,
        )
        output = repurpose_res.get("adapted_text") or source_text
        result = await enforce(
            source_text, output, must_keep_phrases, limit=platform_char_limit(platform)
        )
        attempts.append(
            AttemptRecord(
                attempt_no=attempt_no,
                platform=repurpose_res["platform"],
                tier=repurpose_res.get("tier"),
                model=repurpose_res.get("model"),
                provider=repurpose_res.get("provider"),
                output=output,
                must_keep_passed=result.must_keep_passed,
                judge_verdict=result.judge_verdict,
                judge_confidence=result.judge_confidence,
            )
        )
        if not needs_retry(result) or attempt_no == 2:
            break
        feedback = retry_feedback(result)

    assert result is not None and attempts, "pipeline loop must produce at least one attempt"
    return RepurposeOutcome(
        platform=repurpose_res.get("platform") or platform,
        route_label=route_label,
        attempts=attempts,
        output=attempts[-1].output,
        changes=repurpose_res.get("changes") or [],
        must_keep_passed=result.must_keep_passed,
        feedback=result.feedback,
        judge_verdict=result.judge_verdict,
        judge_confidence=result.judge_confidence,
        tier=repurpose_res.get("tier"),
        model=repurpose_res.get("model"),
    )
