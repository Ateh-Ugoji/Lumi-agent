"""The validated shape of a voice profile and the numbers measured from the posts themselves."""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

PROMPT_VERSION = "voice-v2"

_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
_LINK = re.compile(r"https?://\S+")
_MENTION = re.compile(r"(?<!\w)@\w+")
_HASHTAG = re.compile(r"(?<!\w)#\w+")


def _text(value: Any) -> Any:
    """Models return a list where a sentence was asked for; join it instead of rejecting it."""
    if isinstance(value, list):
        return "; ".join(str(v).strip() for v in value if str(v).strip())
    return value


class VoicePayload(BaseModel):
    """What the model must return. Core fields are required and non-empty; the rest default."""

    archetype_name: str = ""
    creator_bio_summary: str = ""
    perspective: str = ""
    tone: str = Field(min_length=1)
    emoji_use: str = Field(min_length=1)
    hook_style: str = Field(min_length=1)
    vocabulary: str = Field(min_length=1)
    structure: str = Field(min_length=1)
    call_to_action_style: str = ""
    target_length_words: str = ""
    things_they_never_do: str = Field(min_length=1)
    reply_style: str = ""
    representative_excerpts: list[str] = Field(default_factory=list)

    @field_validator(
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
        "reply_style",
        mode="before",
    )
    @classmethod
    def _join_lists(cls, value: Any) -> Any:
        value = _text(value)
        return value.strip() if isinstance(value, str) else value

    @field_validator("representative_excerpts", mode="before")
    @classmethod
    def _excerpt_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [value]
        return value if value is not None else []


CORE_FIELDS = (
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
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verbatim_excerpts(candidates: Sequence[str], captions: Sequence[str]) -> list[str]:
    """Keep only excerpts that really occur in a caption. A paraphrase is a fabricated quote."""
    haystack = [_norm(c) for c in captions]
    kept: list[str] = []
    for excerpt in candidates:
        needle = _norm(excerpt)
        if (
            needle
            and any(needle in h for h in haystack)
            and excerpt.strip() not in kept
        ):
            kept.append(excerpt.strip())
    return kept[:3]


def measure(captions: Sequence[str]) -> dict[str, float | int]:
    """Deterministic style counters. Nothing here comes from a model."""
    n = len(captions)
    if n == 0:
        return {"posts": 0}
    words = [len(c.split()) for c in captions]
    return {
        "posts": n,
        "median_words": float(statistics.median(words)),
        "min_words": min(words),
        "max_words": max(words),
        "emoji_per_post": round(sum(len(_EMOJI.findall(c)) for c in captions) / n, 2),
        "share_with_question": round(sum("?" in c for c in captions) / n, 2),
        "share_multiline": round(sum("\n" in c.strip() for c in captions) / n, 2),
        "share_with_hashtag": round(
            sum(bool(_HASHTAG.search(c)) for c in captions) / n, 2
        ),
        "share_with_link": round(sum(bool(_LINK.search(c)) for c in captions) / n, 2),
        "share_with_mention": round(
            sum(bool(_MENTION.search(c)) for c in captions) / n, 2
        ),
    }
