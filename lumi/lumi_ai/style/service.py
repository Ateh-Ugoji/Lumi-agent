"""Keeps a profile's voice current: learns from posts, or from answers when posts are scarce."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from lumi_ai.agent.support import Completer
from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    Platform,
    PostOut,
    PostStore,
    VoiceProfileOut,
    VoiceStore,
)
from lumi_ai.style.extract import extract_voice, voice_from_answers

log = logging.getLogger(__name__)

Status = Literal["created", "kept", "needs_style_questions", "failed"]


@dataclass(frozen=True, slots=True)
class VoiceRefresh:
    status: Status
    voice: VoiceProfileOut | None = None
    reason: str | None = None
    posts_found: int = 0


def authentic_originals(posts: Sequence[PostOut]) -> list[PostOut]:
    """Own, complete, original writing. Replies and retweets never teach the main voice."""
    return [
        p
        for p in posts
        if p.text.strip()
        and p.kind in (None, "original", "quote")
        and not p.text_truncated
        and not p.is_deleted_suspect
        and not p.text.lstrip().startswith(("RT @", "@"))
    ]


def spread_sample(posts: Sequence[PostOut], limit: int) -> list[PostOut]:
    """``limit`` posts spread evenly over the whole history, oldest first."""
    ordered = sorted(posts, key=lambda p: p.published_at)
    if len(ordered) <= limit:
        return ordered
    step = len(ordered) / limit
    return [ordered[int(i * step)] for i in range(limit)]


class StyleService:
    def __init__(
        self,
        llm: Completer,
        posts: PostStore,
        voice: VoiceStore,
        config: AIConfig | None = None,
    ) -> None:
        self._llm = llm
        self._posts = posts
        self._voice = voice
        self._cfg = config or AIConfig()

    async def refresh_voice(
        self, profile_id: int, platform: Platform | None = None
    ) -> VoiceRefresh:
        """Learn the voice (of one platform, or the general one) from the user's own posts."""
        cfg = self._cfg
        posts = authentic_originals(
            await self._posts.list_posts(
                profile_id, platform=platform, limit=cfg.voice_corpus_limit
            )
        )
        if len(posts) < cfg.voice_min_posts:
            return VoiceRefresh(
                "needs_style_questions",
                reason=(
                    f"only {len(posts)} usable posts, need at least {cfg.voice_min_posts}"
                ),
                posts_found=len(posts),
            )
        sample = spread_sample(posts, cfg.voice_sample_posts)
        activity = await self._posts.list_activity(
            profile_id, kind="reply", limit=cfg.voice_reply_samples
        )
        replies = [
            a.text
            for a in activity
            if a.kind == "reply"
            and a.text.strip()
            and (platform is None or a.platform == platform)
        ]
        prior = await self._voice.current_voice(profile_id, platform)
        try:
            payload = await extract_voice(
                self._llm,
                [p.text for p in sample],
                replies=replies,
                prior=prior.payload if prior else None,
                prior_version=prior.version if prior else None,
                platform=platform,
            )
        except Exception as exc:  # noqa: BLE001 - reported to the caller, nothing is stored
            log.warning("voice extraction failed for profile %s: %s", profile_id, exc)
            return VoiceRefresh("failed", reason=str(exc), posts_found=len(posts))
        saved = await self._voice.save_voice(
            profile_id, platform, payload, "posts", [p.id for p in sample]
        )
        return VoiceRefresh("created", saved, posts_found=len(posts))

    async def build_from_answers(self, profile_id: int) -> VoiceRefresh:
        """Cold start. Never overwrites a voice learned from posts."""
        current = await self._voice.current_voice(profile_id, None)
        if current is not None and current.source == "posts":
            return VoiceRefresh(
                "kept", current, reason="a voice learned from posts exists"
            )
        answers = {
            a.question_key: a.answer
            for a in await self._voice.list_style_answers(profile_id)
        }
        if not answers:
            return VoiceRefresh(
                "needs_style_questions", reason="no style answers stored"
            )
        try:
            payload = await voice_from_answers(self._llm, answers)
        except Exception as exc:  # noqa: BLE001
            log.warning("voice from answers failed for profile %s: %s", profile_id, exc)
            return VoiceRefresh("failed", reason=str(exc))
        saved = await self._voice.save_voice(profile_id, None, payload, "questions", [])
        return VoiceRefresh("created", saved)

    async def ensure_voice(self, profile_id: int) -> VoiceRefresh:
        """Bootstrap step: posts first, answers second, nothing when neither exists."""
        refreshed = await self.refresh_voice(profile_id)
        if refreshed.status != "needs_style_questions":
            return refreshed
        cold = await self.build_from_answers(profile_id)
        if cold.status == "needs_style_questions":
            return VoiceRefresh(
                "needs_style_questions",
                reason=refreshed.reason,
                posts_found=refreshed.posts_found,
            )
        return cold
