import json
import re
from typing import Any

import neatlogs
from pydantic import BaseModel, Field

from app.agent.providers import chat_completion_with_fallback
from app.config import get_settings


class VoiceProfilePayload(BaseModel):
    posts_analyzed_count: int = Field(default=0, description="Total number of post captions analyzed")
    archetype_name: str = Field(
        default="Social Creator", description="Derived style persona (e.g. Pragmatic Builder, Community Weaver, Data Tactician)"
    )
    creator_bio_summary: str = Field(
        default="", description="Concise 1-2 sentence portrait of who this person is, their domain, role, and world"
    )
    perspective: str = Field(
        default="First-person", description="Point of view used (e.g. First-person personal, Second-person direct, Third-person objective)"
    )
    tone: str = Field(description="Primary and secondary tone (e.g. bold, witty, sarcastic, authoritative)")
    emoji_use: str = Field(description="Frequency, favorite emojis, and placement patterns (or explicit prohibition)")
    hook_style: str = Field(description="Typical first-line structure, contrarian openings, questions, etc.")
    vocabulary: str = Field(description="Preferred terms, slang, industry lingo, sentence cadence")
    structure: str = Field(description="Paragraph length, line break frequency, bullet usage, punctuation habits")
    call_to_action_style: str = Field(
        default="None", description="How posts conclude (e.g. asking a question, link in bio/thread, statement only)"
    )
    target_length_words: str = Field(
        default="15-40 words", description="Typical word count range per post"
    )
    things_they_never_do: str | list[str] = Field(
        description="Explicit anti-patterns (no hashtags, no corporate buzzwords, etc.)"
    )
    reply_style: str = Field(
        default="",
        description="How they talk in replies (conversational register) — derived from reply samples, empty when none",
    )
    representative_excerpts: list[str] = Field(
        default_factory=list, description="2-3 standout short snippets that embody the voice"
    )

    def to_clean_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        if isinstance(data.get("things_they_never_do"), list):
            data["things_they_never_do"] = "; ".join(data["things_they_never_do"])
        return data


VOICE_EXTRACTION_SYSTEM_PROMPT = """You are an expert ghostwriter and voice analyst for X (Twitter) and social media creators.
Analyze the provided user posts and derive their unique, actionable writing voice profile.

You must respond with valid JSON matching this schema:
{
  "archetype_name": "A punchy, accurate title for their voice persona (e.g. 'The Pragmatic Builder', 'The Community Connector', 'The Contrarian Analyst')",
  "creator_bio_summary": "A concise 1-2 sentence portrait of who this creator is, their niche/industry, what they care about, and their persona in the ecosystem (e.g. 'Tech founder & Web3 builder in Lagos who talks about startup hustle, network building, and hackathons with blunt wit.')",
  "perspective": "Point of view style (e.g. 'First-person personal ('I', 'my')', 'Second-person advisory ('you')')",
  "tone": "Descriptive summary of attitude and energy (e.g. punchy, cynical, high conviction, playful)",
  "emoji_use": "Exact emoji behavior (e.g. 'Never uses emojis' or 'Uses only 🔥 and 💀 at the end of tweets')",
  "hook_style": "How they capture attention in line 1 (e.g. contrarian statement, short question, event context)",
  "vocabulary": "Word choice tendencies (e.g. tech insider terms, avoids buzzwords, casual phrasing)",
  "structure": "Visual and syntactic layout (e.g. fragmented sentences with line breaks, compact one-liners)",
  "call_to_action_style": "How they close posts (e.g. open questions, invitation to reply, no CTA/ends on statement)",
  "target_length_words": "Estimated word count range per post (e.g. '10-25 words' or '30-60 words')",
  "things_they_never_do": "Clear taboos (e.g. never uses hashtags, never asks for likes, never uses formal greetings)",
  "reply_style": "One sentence on how they talk in replies when REPLY SAMPLES are provided (shorter? warmer? more direct? — empty string if no reply samples)",
  "representative_excerpts": ["2 or 3 short quotes from the posts that best capture the style"]
}

Be specific, observant, and faithful to their actual cadence. Return ONLY JSON."""


def _heuristic_voice_extraction(captions: list[str]) -> dict[str, Any]:
    """Deterministic fallback when no LLM API key is provided or when in offline testing."""
    total_posts = len(captions)
    if total_posts == 0:
        return {
            "posts_analyzed_count": 0,
            "archetype_name": "Neutral Broadcaster",
            "creator_bio_summary": "Active social media creator sharing updates and commentary.",
            "perspective": "Third-person / objective",
            "tone": "neutral, direct",
            "emoji_use": "minimal",
            "hook_style": "direct statement",
            "vocabulary": "concise, standard English",
            "structure": "short 1-2 sentence posts",
            "call_to_action_style": "None",
            "target_length_words": "10-30 words",
            "things_they_never_do": "no excessive hashtags or spam",
            "representative_excerpts": [],
        }

    # Count emojis
    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]", flags=re.UNICODE
    )
    all_text = " ".join(captions)
    emojis_found = emoji_pattern.findall(all_text)
    emoji_freq = len(emojis_found) / max(1, total_posts)

    if emoji_freq == 0:
        emoji_use = "Never uses emojis. Strictly plain text."
    elif emoji_freq < 1:
        emoji_use = f"Sparse emoji use. Occasional use of {set(emojis_found[:3])}."
    else:
        emoji_use = f"Frequent emoji use ({emoji_freq:.1f} per post). Common: {set(emojis_found[:5])}."

    # Avg sentence length and punctuation
    words_per_post = [len(c.split()) for c in captions]
    avg_words = sum(words_per_post) / max(1, len(words_per_post))

    has_questions = any("?" in c for c in captions)
    has_exclamations = any("!" in c for c in captions)
    has_linebreaks = any("\n" in c for c in captions)
    has_first_person = any(re.search(r"\b(i|my|we|me)\b", c.lower()) for c in captions)

    tone_traits = []
    if avg_words < 15:
        tone_traits.append("punchy, concise")
    else:
        tone_traits.append("informative, detailed")

    if has_questions:
        tone_traits.append("inquisitive")
    if not has_exclamations:
        tone_traits.append("calm, understated")
    else:
        tone_traits.append("enthusiastic")

    structure_desc = (
        "Multi-line with spacing" if has_linebreaks else "Single paragraph / compact"
    )
    hook_desc = "Starts with question or bold hook" if has_questions else "Direct declarative opening"
    perspective_desc = "First-person personal" if has_first_person else "Direct / observational"
    archetype_desc = "Conversational Creator" if has_first_person else "Direct Informer"
    bio_desc = "Community-driven creator sharing project milestones and observations." if has_first_person else "Focused domain commentator sharing insights."

    return {
        "posts_analyzed_count": total_posts,
        "archetype_name": archetype_desc,
        "creator_bio_summary": bio_desc,
        "perspective": perspective_desc,
        "tone": ", ".join(tone_traits),
        "emoji_use": emoji_use,
        "hook_style": hook_desc,
        "vocabulary": "natural social phrasing, conversational tone",
        "structure": f"{structure_desc}; average length ~{int(avg_words)} words per post",
        "call_to_action_style": "Occasional rhetorical question" if has_questions else "None / statement-based",
        "target_length_words": f"{max(5, int(avg_words - 10))}-{int(avg_words + 15)} words",
        "things_they_never_do": "never uses generic corporate PR language or spam hashtags",
        "representative_excerpts": captions[:2],
    }


def _format_prior_profile(prior: dict[str, Any], version: int | None) -> str:
    """Render a prior voice profile as a compact continuity block for the prompt."""
    lines: list[str] = []
    if version is not None:
        lines.append(f"Version: {version}")
    for key in (
        "archetype_name",
        "creator_bio_summary",
        "perspective",
        "tone",
        "emoji_use",
        "hook_style",
        "vocabulary",
        "structure",
        "call_to_action_style",
        "target_length_words",
        "things_they_never_do",
    ):
        val = prior.get(key)
        if val:
            lines.append(f"{key}: {val}")
    return "\n".join(lines)


@neatlogs.span(kind="CHAIN", name="extract_voice_from_captions")
async def extract_voice_from_captions(
    captions: list[str],
    prior_payload: dict[str, Any] | None = None,
    prior_version: int | None = None,
    reply_captions: list[str] | None = None,
) -> dict[str, Any]:
    """Analyzes a list of post captions and returns a structured voice profile payload.

    When prior_payload is provided, it is injected as continuity context so re-runs
    stay stable instead of drifting — the model is told to remain consistent unless
    the posts clearly show the voice has evolved. reply_captions, when provided,
    feed the optional reply_style field only — never the main voice fields.
    """
    settings = get_settings()

    # If no LLM keys are configured, use heuristic extraction immediately
    if not settings.groq_api_key and not settings.openrouter_api_key:
        return _heuristic_voice_extraction(captions)

    posts_block = "\n\n---\n\n".join(
        f"Post {idx + 1}:\n{caption.strip()}" for idx, caption in enumerate(captions)
    )

    user_prompt = f"Analyze the following {len(captions)} posts from the user:\n\n{posts_block}"
    if reply_captions:
        replies_block = "\n\n---\n\n".join(
            f"Reply {idx + 1}:\n{caption.strip()}" for idx, caption in enumerate(reply_captions)
        )
        user_prompt += (
            "\n\nREPLY SAMPLES (the user's own replies — use these ONLY to fill reply_style,"
            " not for any other voice field):\n\n" + replies_block
        )
    if prior_payload:
        prior_block = _format_prior_profile(prior_payload, prior_version)
        if prior_block:
            user_prompt += (
                "\n\nPRIOR VOICE PROFILE (for continuity — stay consistent with it unless"
                " the posts clearly show the voice has evolved):\n" + prior_block
            )

    messages = [
        {"role": "system", "content": VOICE_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        completion = await chat_completion_with_fallback(messages, tools=[])
        raw_content = completion.choices[0].message.content or "{}"

        # Clean markdown codeblocks if model wrapped in ```json
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            data = data[0]

        data["posts_analyzed_count"] = len(captions)
        validated = VoiceProfilePayload(**data)
        return validated.to_clean_dict()


    except Exception:  # noqa: BLE001
        # Fall back to heuristic extraction on any LLM or JSON parsing error
        return _heuristic_voice_extraction(captions)

