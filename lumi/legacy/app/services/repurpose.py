"""Platform recaptioning service.

Adapts a source draft caption across platforms (X, LinkedIn, TikTok, Instagram)
using specialized system prompts that respect platform conventions while
faithfully preserving the user's authentic voice profile and must-keep items.
"""

import json
import logging
import re
from typing import Any

import neatlogs
from pydantic import BaseModel, Field

from app.agent.providers import TIER_MODELS, chat_completion_with_provider
from app.models.voice import VoiceProfile
from app.services import jev
from app.services.metrics import X_CHAR_LIMIT

log = logging.getLogger(__name__)

ROUTE_TIERS = {"easy": "small", "standard": "large", "hard": "large"}
HARD_PROTECTED_ITEM_COUNT = 3
_PROTECTED_TOKEN = re.compile(r"https?://\S+|@\w+")

DIFFICULTY_CRITERIA = {
    "easy": "Light restyle on the same platform: fits the length limit and has nothing that must survive verbatim.",
    "standard": "Moderate rewrite: a platform change, or one or two links, @handles, or required phrases to preserve.",
    "hard": (
        "Heavily constrained: the source must be compressed to fit the platform limit, "
        "or many links, @handles, numbers, or required phrases must survive intact."
    ),
}


def classify_difficulty_by_rule(source_text: str, platform: str, must_keep_phrases: list[str]) -> str:
    target = platform.lower().strip()
    protected_items = len(must_keep_phrases) + len(_PROTECTED_TOKEN.findall(source_text))

    if target == "x" and len(source_text) > X_CHAR_LIMIT:
        return "hard"
    if protected_items >= HARD_PROTECTED_ITEM_COUNT:
        return "hard"
    if target == "x" and protected_items == 0:
        return "easy"
    return "standard"


@neatlogs.span(kind="TOOL", tool_name="classify_difficulty_jev")
async def _classify_difficulty_jev(source_text: str, platform: str, must_keep_phrases: list[str]) -> str | None:
    target = platform.lower().strip()
    choice = await jev.ask_choice(
        state={
            "source_caption": source_text,
            "source_length": len(source_text),
            "target_platform": target,
            "target_length_limit": X_CHAR_LIMIT if target == "x" else None,
            "must_keep_phrases": must_keep_phrases,
        },
        name="difficulty",
        instructions="How hard is it to rewrite this caption for the target platform?",
        criteria=DIFFICULTY_CRITERIA,
    )
    if choice in DIFFICULTY_CRITERIA:
        return choice
    return None


async def classify_difficulty(source_text: str, platform: str, must_keep_phrases: list[str]) -> str:
    """Label a repurpose request easy/standard/hard — Jev first, deterministic rule if Jev is unavailable."""
    choice = None
    try:
        choice = await _classify_difficulty_jev(source_text, platform, must_keep_phrases)
    except Exception as exc:  # noqa: BLE001
        log.warning("Jev difficulty classification raised: %s", exc)
    if choice is not None:
        return choice
    log.warning("Jev difficulty classification unavailable, using rule-based fallback")
    return classify_difficulty_by_rule(source_text, platform, must_keep_phrases)

PLATFORM_RULES = {
    "x": (
        "PLATFORM: X (Twitter)\n"
        "- Length: Under 280 characters visible. Keep it punchy and concise.\n"
        "- Structure: Fragmented lines, double line breaks for visual spacing, short punchy hook.\n"
        "- Hashtags: 0 to 1 maximum (never clutter with hashtag spam).\n"
        "- CTA: Conversational hook, question, or peer discussion prompt."
    ),
    "linkedin": (
        "PLATFORM: LinkedIn\n"
        "- Length: 800-2,000 characters. Expand the thought into an insightful narrative.\n"
        "- Structure: High-curiosity first 2 lines (before the 'see more' fold). Use line breaks and bullet points for takeaways.\n"
        "- Tone: Professional reflection, business/engineering lessons, transparent founder vulnerability.\n"
        "- Hashtags: 3 to 5 relevant industry hashtags placed cleanly at the very end.\n"
        "- CTA: Ask a genuine professional peer question (e.g. 'How do you handle this in your stack?')."
    ),
    "tiktok": (
        "PLATFORM: TikTok / Reels\n"
        "- Length: Short and snappy (50-150 words). The caption is secondary to video content.\n"
        "- Structure: Instant curiosity hook ('Wait till the end...', 'How we solved X in 24 hours').\n"
        "- Tone: High energy, casual, entertaining, relatable.\n"
        "- Hashtags: 3 to 5 mixed trending and niche tags (#buildinpublic, #tech, #startup).\n"
        "- CTA: 'Drop your thoughts in comments' or 'Follow for part 2'."
    ),
    "instagram": (
        "PLATFORM: Instagram\n"
        "- Length: Medium (150-400 words). Acts as a storytelling companion to photos/carousels.\n"
        "- Structure: Clean opening line, narrative paragraph, emotional reflection.\n"
        "- Tone: Relatable, visually descriptive, energetic.\n"
        "- Hashtags: 3 to 8 relevant hashtags separated at the end with a dot separator.\n"
        "- CTA: Invite likes, saves, or comments."
    ),
}


class ChangeRecord(BaseModel):
    change: str = Field(description="Short description of what was changed")
    reason: str = Field(description="Why the change was made (tied to platform rule or voice trait)")


class PlatformRepurposeOutput(BaseModel):
    platform: str
    adapted_text: str
    changes: list[ChangeRecord] = Field(default_factory=list)


REPURPOSE_SYSTEM_PROMPT = """You are Lumi's universal social media caption adaptation engine.
Your task is to take a source thought or draft and adapt it into a high-performing post for {platform}.

You apply the universal, empirical mechanics of how the top 100+ creators structure posts on each platform:
- X: Punchy vertical layout, single thoughts separated by double line breaks, zero fluff, sharp peer hook.
- LinkedIn: High-curiosity opening before the fold, generous line spacing, structured lessons/takeaways, 3-5 trailing hashtags.
- TikTok/Reels: Instant curiosity hook, fast pace, informal energy, comment prompt.
- Instagram: Visual storytelling companion, clean paragraph breaks, genuine reflection.

RULES:
1. UNIVERSAL PLATFORM CONVENTIONS: Adhere strictly to the platform's format, character limits, line spacing, and CTA conventions below.
2. VOICE & THOUGHT PRESERVATION: Maintain the author's core insight, intent, and authentic tone. Do NOT dilute their argument with corporate cliches.
3. MUST-KEEP ITEMS: Any URLs, @mentions, numbers, dates, and named entities MUST remain intact.

CREATOR VOICE CONTEXT:
{voice_profile_context}

UNIVERSAL {platform} CONVENTIONS:
{platform_rules}

Return valid JSON matching this schema:
{{
  "platform": "{platform}",
  "adapted_text": "The platform-adapted caption",
  "changes": [
    {{"change": "Summary of structural adaptation", "reason": "Universal platform rule applied"}}
  ]
}}

Return ONLY valid JSON."""


def _format_voice_context(profile: VoiceProfile | None) -> str:
    if profile is None or not profile.payload:
        return "Tone: authentic, conversational founder. Avoid corporate PR speak."

    p = profile.payload
    lines = [
        f"Archetype: {p.get('archetype_name', 'Tech Creator')}",
        f"Perspective: {p.get('perspective', 'First-person')}",
        f"Tone: {p.get('tone', 'casual, direct')}",
        f"Emoji Behavior: {p.get('emoji_use', 'minimal')}",
        f"Vocabulary: {p.get('vocabulary', 'conversational')}",
        f"Anti-patterns (Things they NEVER do): {p.get('things_they_never_do', 'No corporate buzzwords')}",
    ]
    if p.get("representative_excerpts"):
        lines.append(f"Representative Quotes: {json.dumps(p.get('representative_excerpts'))}")
    return "\n".join(lines)


@neatlogs.span(kind="CHAIN", name="generate_platform_repurpose")
async def generate_platform_repurpose(
    source_text: str,
    platform: str = "x",
    voice_profile: VoiceProfile | None = None,
    must_keep_phrases: list[str] | None = None,
    tier: str = "large",
    revision_feedback: str | None = None,
) -> dict[str, Any]:
    """Rewrite a caption for a specific platform in the user's authentic voice.

    Besides the rewrite, returns `tier`, `model`, and `provider` (the latter two None if no LLM answered).
    `revision_feedback` appends judge/enforcement notes from a previous attempt so the
    retry can be targeted.
    """
    target_platform = platform.lower().strip()
    rules = PLATFORM_RULES.get(target_platform, PLATFORM_RULES["x"])
    voice_context = _format_voice_context(voice_profile)

    system_prompt = REPURPOSE_SYSTEM_PROMPT.format(
        platform=target_platform.upper(),
        voice_profile_context=voice_context,
        platform_rules=rules,
    )

    must_keep_note = ""
    if must_keep_phrases:
        must_keep_note = f"\nMandatory phrases to preserve: {', '.join(must_keep_phrases)}"

    user_prompt = f"Source Caption to Repurpose:\n{source_text}{must_keep_note}"
    if revision_feedback:
        user_prompt += (
            "\n\nRevision required: your previous attempt was rejected. Fix this:\n"
            f"{revision_feedback}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    routing = {"tier": tier, "model": None, "provider": None}
    try:
        completion, provider = await chat_completion_with_provider(messages, tools=[], model=TIER_MODELS[tier])
        routing.update(model=completion.model, provider=provider)
        raw = completion.choices[0].message.content or "{}"
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            data = data[0]

        validated = PlatformRepurposeOutput(**data)
        return {**validated.model_dump(), **routing}
    except Exception:  # noqa: BLE001
        # Fallback if LLM or parsing fails
        return {
            "platform": target_platform,
            "adapted_text": source_text,
            "changes": [
                {"change": "Kept original text", "reason": "Fallback mode"}
            ],
            **routing,
        }
