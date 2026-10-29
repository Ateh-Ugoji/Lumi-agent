import json
import logging
from dataclasses import dataclass

import neatlogs
import openai
from openai import AsyncOpenAI
from typesafe_sdk import TypeSafeError

from app.agent.providers import GROQ_BASE_URL, TIER_MODELS
from app.config import get_settings
from app.services import jev
from app.services.metrics import X_CHAR_LIMIT

log = logging.getLogger(__name__)

GROQ_JUDGE_MODEL = TIER_MODELS["small"]


@dataclass
class _CheckResult:
    passed: bool
    feedback: str | None = None


@dataclass
class EnforcementResult:
    must_keep_passed: bool
    feedback: str | None = None
    judge_verdict: str | None = None
    judge_confidence: float | None = None
    judge_source: str | None = None


def check_length(text: str, limit: int = X_CHAR_LIMIT) -> _CheckResult:
    if len(text) > limit:
        return _CheckResult(passed=False, feedback=f"{len(text)} chars exceeds the {limit} char limit")
    return _CheckResult(passed=True)


def check_must_keep(text: str, must_keep_phrases: list[str]) -> _CheckResult:
    missing = [phrase for phrase in must_keep_phrases if phrase.lower() not in text.lower()]
    if missing:
        return _CheckResult(passed=False, feedback=f"missing required phrase(s): {', '.join(missing)}")
    return _CheckResult(passed=True)


@neatlogs.span(kind="GUARDRAIL", name="judge_caption_jev")
async def _judge_jev(original: str, rewrite: str) -> tuple[str, float] | None:
    scores = await jev.ask_noul(
        state={"original": original, "rewrite": rewrite},
        questions={
            "preserves_meaning": (
                "Does the rewrite preserve the original caption's meaning, claims, and intent, "
                "even though the wording and voice may differ?"
            ),
        },
    )
    if scores is None:
        return None
    noul = scores["preserves_meaning"]
    verdict = "yes" if noul >= 0.5 else "no"
    return verdict, noul


@neatlogs.span(kind="GUARDRAIL", name="judge_caption_llm_fallback")
async def _judge_llm_fallback(original: str, rewrite: str) -> tuple[str, float]:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL)
    response = await client.chat.completions.create(
        model=GROQ_JUDGE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict judge. Decide whether a rewrite preserves the original caption's "
                    "meaning, claims, and intent (wording and voice may differ). "
                    'Respond with ONLY a JSON object: {"preserves": true/false, "confidence": 0.0-1.0}'
                ),
            },
            {
                "role": "user",
                "content": f"Original: {original}\n\nRewrite: {rewrite}",
            },
        ],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    parsed = json.loads(raw)
    verdict = "yes" if parsed["preserves"] else "no"
    confidence = float(parsed["confidence"])
    return verdict, confidence


async def judge_caption(original: str, rewrite: str) -> tuple[str, float, str]:
    """Returns (verdict, confidence, source) where source is 'jev' or 'llm_fallback'."""
    jev_result = None
    try:
        jev_result = await _judge_jev(original, rewrite)
    except Exception as exc:  # noqa: BLE001
        log.warning("Jev judge raised: %s", exc)
    if jev_result is not None:
        verdict, confidence = jev_result
        return verdict, confidence, "jev"
    log.warning("Jev judge unavailable, falling back to LLM judge")

    try:
        verdict, confidence = await _judge_llm_fallback(original, rewrite)
        return verdict, confidence, "llm_fallback"
    except (openai.APIError, json.JSONDecodeError, KeyError, ValueError):
        log.warning("LLM fallback judge also failed, skipping judge")
        raise


JUDGE_CONFIDENCE_RETRY_THRESHOLD = 0.8

# Per-platform upper bounds for the length check. Using the X limit for every
# platform made any >280-char LinkedIn/TikTok/Instagram rewrite fail by
# construction (and skip the judge), triggering a pointless regeneration.
PLATFORM_CHAR_LIMITS = {
    "x": X_CHAR_LIMIT,
    "linkedin": 3000,
    "tiktok": 3000,
    "instagram": 3000,
}


def platform_char_limit(platform: str) -> int:
    return PLATFORM_CHAR_LIMITS.get(platform.lower().strip(), X_CHAR_LIMIT)


def needs_retry(result: "EnforcementResult") -> bool:
    """True when the attempt should be regenerated once with feedback.

    Deterministic failures (length / missing must-keep) always retry; judge
    failures retry on a 'no' verdict or confidence below the spec'd 0.8.
    """
    if not result.must_keep_passed:
        return True
    if result.judge_verdict is None:
        return False
    if result.judge_verdict == "no":
        return True
    return result.judge_confidence is not None and result.judge_confidence < JUDGE_CONFIDENCE_RETRY_THRESHOLD


def retry_feedback(result: "EnforcementResult") -> str:
    """Human-readable note appended to the regeneration prompt."""
    parts: list[str] = []
    if not result.must_keep_passed and result.feedback:
        parts.append(f"Previous attempt failed enforcement: {result.feedback}.")
    if result.judge_verdict is not None and (
        result.judge_verdict == "no"
        or (result.judge_confidence is not None and result.judge_confidence < JUDGE_CONFIDENCE_RETRY_THRESHOLD)
    ):
        confidence = f"{result.judge_confidence:.2f}" if result.judge_confidence is not None else "n/a"
        parts.append(
            "A semantic judge flagged the previous rewrite "
            f"(verdict={result.judge_verdict}, confidence={confidence}): "
            "preserve the source's meaning, claims, and intent much more faithfully."
        )
    return " ".join(parts)


@neatlogs.span(kind="CHAIN", name="enforce")
async def enforce(
    original: str,
    rewrite: str,
    must_keep_phrases: list[str],
    limit: int = X_CHAR_LIMIT,
) -> EnforcementResult:
    for check in (check_length(rewrite, limit), check_must_keep(rewrite, must_keep_phrases)):
        if not check.passed:
            return EnforcementResult(must_keep_passed=False, feedback=check.feedback)

    try:
        verdict, confidence, source = await judge_caption(original, rewrite)
        return EnforcementResult(
            must_keep_passed=True,
            judge_verdict=verdict,
            judge_confidence=confidence,
            judge_source=source,
        )
    except (TypeSafeError, openai.APIError, json.JSONDecodeError, KeyError, ValueError):
        log.warning("All judges failed, relying on deterministic checks only")
        return EnforcementResult(
            must_keep_passed=True,
            feedback="judge unavailable — flagged for manual review",
            judge_source="none",
        )
