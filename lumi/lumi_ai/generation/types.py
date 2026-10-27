"""Shapes shared by the generation steps. Plain data, no behaviour that talks to a provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from lumi_ai.ports import AttemptIn, Platform, Tier

Mode = Literal["repurpose", "topic"]
Difficulty = Literal["easy", "standard", "hard"]


@dataclass(frozen=True, slots=True)
class GenerationBrief:
    """What the user asked for. In ``repurpose`` mode ``source_text`` is the caption to adapt."""

    profile_id: int
    platform: Platform
    mode: Mode
    source_text: str | None = None  # topic mode: optional reference material
    topic: str | None = None
    goal: str | None = None
    must_keep: tuple[str, ...] = ()

    @property
    def subject(self) -> str:
        """The text the post is about: what retrieval and ranking compare against."""
        return (self.source_text if self.mode == "repurpose" else self.topic) or ""


@dataclass(frozen=True, slots=True)
class Change:
    change: str
    reason: str


@dataclass(frozen=True, slots=True)
class Draft:
    text: str
    changes: tuple[Change, ...]
    tier: Tier
    model: str
    provider: str
    is_fallback: bool  # the chain had to skip a model to answer this draft


@dataclass(frozen=True, slots=True)
class Review:
    """Verdict on one draft. ``must_keep_passed`` is the deterministic part."""

    must_keep_passed: bool
    failures: tuple[str, ...] = ()
    feedback: str | None = None  # why it failed, or a note for the human
    judge_verdict: Literal["yes", "no"] | None = None
    judge_confidence: float | None = None
    judge_source: str | None = (
        None  # "judge" when a verdict exists, "none" when it was unavailable
    )
    needs_retry: bool = False
    revision_note: str = ""  # what the next attempt must fix


class Reviewer(Protocol):
    """Checks a draft. T8 ships the enforcement reviewer; the quality reviewer plugs in later."""

    async def review(self, brief: GenerationBrief, text: str) -> Review: ...


@dataclass(frozen=True, slots=True)
class ContextUsed:
    """What the writer was given, so the user and the logs can see what the draft rests on."""

    voice: str  # "<platform>", "general" or "none"
    voice_version: int | None
    example_post_ids: tuple[int, ...] = ()
    frameworks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    brief: GenerationBrief
    route_label: Difficulty
    attempts: tuple[AttemptIn, ...]
    reviews: tuple[Review, ...]
    drafts: tuple[Draft, ...]
    chosen: int  # index into attempts
    context: ContextUsed = field(default_factory=lambda: ContextUsed("none", None))
