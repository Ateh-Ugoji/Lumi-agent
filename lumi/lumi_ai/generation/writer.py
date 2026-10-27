"""Asks the model for one draft and checks that the answer is usable. Never invents a draft.

A reply that is not the required JSON object raises :class:`DraftUnusable`; the flow turns that
into feedback for the next attempt. The legacy code returned the unchanged source text as the
"rewrite" in that case, which hid the failure behind a draft that looked fine.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lumi_ai.agent.support import Completer
from lumi_ai.generation.platforms import PlatformRules
from lumi_ai.generation.types import Change, Draft, GenerationBrief
from lumi_ai.json_utils import JSONExtractionError, extract_json_object
from lumi_ai.ports import Tier

SYSTEM = """You are Lumi's ghostwriter. You write one post for {label} in the author's own voice.
Reply with ONE JSON object and nothing else:
{{"text": "the post, ready to publish", "changes": [{{"change": "what you changed or chose", "reason": "which rule or voice trait it serves"}}]}}

RULES
1. Follow the platform rules below. The post must be at most {limit} characters including hashtags and links.
2. Write like the author (voice below), not like a brand. Keep their meaning, claims and intent.
3. Keep every URL, @mention, number, date and name from the source exactly as written, and every mandatory phrase verbatim.
4. Never invent facts, numbers, quotes or stories that the source or the brief does not contain.
5. No em dashes, no filler openers ("In today's world", "Let's dive in"), no emoji unless the voice uses them.

PLATFORM RULES ({label})
{guidance}

AUTHOR VOICE
{voice}"""

_VOICE_FIELDS = (
    ("archetype_name", "Archetype"),
    ("perspective", "Perspective"),
    ("tone", "Tone"),
    ("emoji_use", "Emoji"),
    ("hook_style", "Hooks"),
    ("vocabulary", "Vocabulary"),
    ("structure", "Structure"),
    ("call_to_action_style", "Closing"),
    ("target_length_words", "Typical length"),
    ("things_they_never_do", "Never does"),
)
NO_VOICE = (
    "No voice profile has been learned for this author yet. Write plainly and naturally; "
    "do not claim to imitate them."
)


class DraftUnusable(Exception):
    """The model answered, but not with a usable draft."""


@dataclass(frozen=True, slots=True)
class WriterContext:
    voice_text: str
    examples: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Revision:
    previous: str
    note: str


def format_voice(payload: Mapping[str, Any] | None) -> str:
    if not payload:
        return NO_VOICE
    lines = [
        f"{label}: {payload[key]}" for key, label in _VOICE_FIELDS if payload.get(key)
    ]
    excerpts = payload.get("representative_excerpts")
    if excerpts:
        lines.append(
            f"Quotes in their voice: {json.dumps(list(excerpts), ensure_ascii=False)}"
        )
    return "\n".join(lines) or NO_VOICE


def build_messages(
    brief: GenerationBrief,
    rules: PlatformRules,
    context: WriterContext,
    revision: Revision | None,
) -> list[dict[str, str]]:
    system = SYSTEM.format(
        label=rules.label,
        limit=rules.hard_limit,
        guidance=rules.guidance,
        voice=context.voice_text,
    )
    if brief.mode == "repurpose":
        parts = [f"Source caption to adapt for {rules.label}:\n{brief.source_text}"]
    else:
        parts = [f"Write a {rules.label} post about:\n{brief.topic}"]
        if brief.goal:
            parts.append(f"Goal of the post: {brief.goal}")
        if brief.source_text:
            parts.append(
                f"Reference material to draw from (use only what it says):\n{brief.source_text}"
            )
    if brief.must_keep:
        parts.append("Mandatory phrases, verbatim: " + "; ".join(brief.must_keep))
    if context.examples:
        shown = "\n---\n".join(context.examples)
        parts.append(
            f"Posts the author really wrote (for voice only, never copy):\n{shown}"
        )
    if context.frameworks:
        parts.append(
            "Structures that won in this niche (use as a skeleton, not as words):\n"
            + "\n".join(f"- {f}" for f in context.frameworks)
        )
    if revision is not None:
        parts.append(
            f"Your previous draft was rejected.\nPrevious draft:\n{revision.previous}\n"
            f"Fix this and answer with the corrected JSON object:\n{revision.note}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_draft(raw: str) -> tuple[str, tuple[Change, ...]]:
    try:
        data = extract_json_object(raw)
    except JSONExtractionError as exc:
        raise DraftUnusable(f"the reply was not a JSON object ({exc})") from exc
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise DraftUnusable('the JSON object has no non-empty "text" string')
    changes: list[Change] = []
    raw_changes = data.get("changes")
    if isinstance(raw_changes, Sequence) and not isinstance(raw_changes, str):
        for item in raw_changes:
            if isinstance(item, Mapping) and item.get("change"):
                changes.append(Change(str(item["change"]), str(item.get("reason", ""))))
    return text.strip(), tuple(changes)


class Writer:
    def __init__(self, llm: Completer) -> None:
        self._llm = llm

    async def write(
        self,
        brief: GenerationBrief,
        rules: PlatformRules,
        context: WriterContext,
        *,
        tier: Tier,
        revision: Revision | None = None,
    ) -> Draft:
        result = await self._llm.complete(
            build_messages(brief, rules, context, revision), [], tier=tier
        )
        raw = result.completion.choices[0].message.content or ""
        text, changes = parse_draft(raw)
        return Draft(
            text=text,
            changes=changes,
            tier=tier,
            model=result.model,
            provider=result.provider,
            is_fallback=bool(result.attempts),
        )
