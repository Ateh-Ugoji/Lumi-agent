"""Ask the model for a voice profile, validate it, repair once, never invent one."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from lumi_ai.agent.support import Completer
from lumi_ai.json_utils import JSONExtractionError, extract_json
from lumi_ai.style.errors import VoiceExtractionError
from lumi_ai.style.schema import (
    CORE_FIELDS,
    PROMPT_VERSION,
    VoicePayload,
    measure,
    verbatim_excerpts,
)

log = logging.getLogger(__name__)

_SCHEMA = """{
  "archetype_name": "short, accurate title for the voice persona",
  "creator_bio_summary": "1-2 sentences: who this person is, their field, what they care about",
  "perspective": "point of view used (first person 'I', second person 'you', ...)",
  "tone": "attitude and energy",
  "emoji_use": "exact emoji behaviour, or an explicit 'never'",
  "hook_style": "how line 1 captures attention",
  "vocabulary": "word choice, jargon, sentence cadence",
  "structure": "line breaks, paragraph length, lists, punctuation habits",
  "call_to_action_style": "how posts close; 'none' when they just end",
  "target_length_words": "typical word range, e.g. '10-25 words'",
  "things_they_never_do": "concrete taboos observed in the posts",
  "reply_style": "one sentence on how they talk in replies; empty string when no reply samples",
  "representative_excerpts": ["2 or 3 SHORT quotes copied exactly from the posts"]
}"""

POSTS_SYSTEM = (
    "You are a ghostwriter and voice analyst for social media creators. Read the user's own "
    "posts and describe their real writing voice so another writer could imitate it.\n"
    "Rules: describe only what the posts show; if something is not visible, say 'not observed' "
    "instead of guessing; quote excerpts exactly, never paraphrase them.\n"
    "Reply with ONE JSON object and nothing else, with this shape:\n" + _SCHEMA
)

ANSWERS_SYSTEM = (
    "You are a ghostwriter. The user has too few posts to analyse, so you only have their "
    "own answers to a style questionnaire. Turn the answers into a voice profile. Use only what "
    "the answers say; write 'not stated' for any field they do not cover. representative_excerpts "
    "may only contain text the user pasted themselves, else an empty list.\n"
    "Reply with ONE JSON object and nothing else, with this shape:\n" + _SCHEMA
)

_PRIOR_FIELDS = CORE_FIELDS


def format_prior(prior: Mapping[str, Any], version: int | None) -> str:
    lines = [f"Version: {version}"] if version is not None else []
    for key in _PRIOR_FIELDS:
        value = prior.get(key)
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _numbered(label: str, texts: Sequence[str]) -> str:
    return "\n\n---\n\n".join(
        f"{label} {i + 1}:\n{t.strip()}" for i, t in enumerate(texts)
    )


def build_posts_prompt(
    captions: Sequence[str],
    replies: Sequence[str],
    prior: Mapping[str, Any] | None,
    prior_version: int | None,
    platform: str | None,
) -> str:
    where = f" on {platform}" if platform else ""
    parts = [
        f"Analyse these {len(captions)} posts the user wrote{where}:\n\n"
        + _numbered("Post", captions)
    ]
    if replies:
        parts.append(
            "REPLY SAMPLES (the user's own replies; use them ONLY for reply_style, never for "
            "the other fields):\n\n" + _numbered("Reply", replies)
        )
    if prior:
        block = format_prior(prior, prior_version)
        if block:
            parts.append(
                "PRIOR VOICE PROFILE (stay consistent with it unless the posts clearly show the "
                "voice has evolved):\n" + block
            )
    return "\n\n".join(parts)


async def _ask(llm: Completer, system: str, user: str) -> tuple[VoicePayload, str]:
    """One request plus one repair round. Returns the payload and the model that produced it."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    error = ""
    for attempt in range(2):
        result = await llm.complete(messages, [], tier="large", effort="low")
        raw = result.completion.choices[0].message.content or ""
        try:
            data = extract_json(raw)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
            if not isinstance(data, dict):
                raise JSONExtractionError(
                    f"expected a JSON object, got {type(data).__name__}"
                )
            return VoicePayload.model_validate(data), result.model
        except (JSONExtractionError, ValidationError) as exc:
            error = _short(exc)
            log.warning("voice extraction attempt %d rejected: %s", attempt + 1, error)
            messages += [
                {"role": "assistant", "content": raw[:4000]},
                {
                    "role": "user",
                    "content": (
                        f"That reply was rejected: {error}\nReturn the corrected JSON object "
                        "only, with every required field filled."
                    ),
                },
            ]
    raise VoiceExtractionError(f"the model returned no usable voice profile: {error}")


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:6]
        )
    return str(exc)[:300]


async def extract_voice(
    llm: Completer,
    captions: Sequence[str],
    *,
    replies: Sequence[str] = (),
    prior: Mapping[str, Any] | None = None,
    prior_version: int | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Voice payload for real posts. Raises :class:`VoiceExtractionError` on failure."""
    if not captions:
        raise VoiceExtractionError("no posts to analyse")
    user = build_posts_prompt(captions, replies, prior, prior_version, platform)
    payload, model = await _ask(llm, POSTS_SYSTEM, user)
    data = payload.model_dump()
    data["representative_excerpts"] = verbatim_excerpts(
        payload.representative_excerpts, captions
    )
    if not replies:
        data["reply_style"] = ""  # nothing to derive it from
    data["posts_analyzed_count"] = len(captions)
    data["measured"] = measure(captions)
    data["extraction"] = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "source": "posts",
    }
    return data


async def voice_from_answers(
    llm: Completer, answers: Mapping[str, str]
) -> dict[str, Any]:
    """Cold-start voice payload built only from the user's questionnaire answers."""
    if not any(a.strip() for a in answers.values()):
        raise VoiceExtractionError("no answers to build a voice from")
    user = "QUESTIONNAIRE ANSWERS (JSON):\n" + json.dumps(
        dict(answers), ensure_ascii=False
    )
    payload, model = await _ask(llm, ANSWERS_SYSTEM, user)
    data = payload.model_dump()
    pasted = [answers[k] for k in ("example",) if answers.get(k)]
    data["representative_excerpts"] = verbatim_excerpts(
        payload.representative_excerpts, pasted
    )
    data["reply_style"] = ""
    data["posts_analyzed_count"] = 0
    data["extraction"] = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "source": "questions",
    }
    return data
