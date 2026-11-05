"""``VoiceStore``: versioned voice profiles (one current per platform) and the style answers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from django.db import transaction
from django.db.models import Max

from apps.intelligence.models import (
    GENERAL,
    StyleAnswer,
    VoiceProfile,
    VoiceProfileExample,
    VoiceSource,
)
from apps.intelligence.repos.aio import aio
from lumi_ai.ports import StyleAnswerIn, VoiceProfileOut


def _out(row: VoiceProfile) -> VoiceProfileOut:
    examples = row.examples.order_by("position").values_list("post_id", flat=True)
    return VoiceProfileOut(
        id=row.pk,
        profile_id=row.profile_id,
        platform=None if row.platform == GENERAL else row.platform,  # type: ignore[arg-type]
        version=row.version,
        payload=row.payload,
        source=row.source,  # type: ignore[arg-type]
        example_post_ids=tuple(examples),
        created_at=row.created_at,
    )


class VoiceRepo:
    @aio
    def current_voice(
        self, profile_id: int, platform: str | None = None
    ) -> VoiceProfileOut | None:
        row = VoiceProfile.objects.filter(
            profile_id=profile_id, platform=platform or GENERAL, is_current=True
        ).first()
        return _out(row) if row else None

    @aio
    def save_voice(
        self,
        profile_id: int,
        platform: str | None,
        payload: Mapping[str, Any],
        source: Literal["posts", "questions"],
        example_post_ids: Sequence[int],
        *,
        model: str = "",
        prompt_version: str = "",
    ) -> VoiceProfileOut:
        """Add the next version and make it the current one, atomically."""
        key = platform or GENERAL
        with transaction.atomic():
            siblings = VoiceProfile.objects.select_for_update().filter(
                profile_id=profile_id, platform=key
            )
            last = siblings.aggregate(top=Max("version"))["top"] or 0
            siblings.filter(is_current=True).update(is_current=False)
            row = VoiceProfile.objects.create(
                profile_id=profile_id,
                platform=key,
                version=last + 1,
                is_current=True,
                source=VoiceSource(source),
                payload=dict(payload),
                model=model,
                prompt_version=prompt_version,
            )
            VoiceProfileExample.objects.bulk_create(
                [
                    VoiceProfileExample(voice_profile=row, post_id=post_id, position=i)
                    for i, post_id in enumerate(dict.fromkeys(example_post_ids))
                ]
            )
        return _out(row)

    @aio
    def save_style_answers(
        self, profile_id: int, answers: Sequence[StyleAnswerIn]
    ) -> None:
        with transaction.atomic():
            for answer in answers:
                StyleAnswer.objects.update_or_create(
                    profile_id=profile_id,
                    question_key=answer.question_key,
                    defaults={"answer": answer.answer},
                )

    @aio
    def list_style_answers(self, profile_id: int) -> list[StyleAnswerIn]:
        rows = StyleAnswer.objects.filter(profile_id=profile_id).order_by("id")
        return [StyleAnswerIn(r.question_key, r.answer) for r in rows]


def profiles_with_voice(profile_ids: Sequence[int]) -> set[int]:
    """Ids among ``profile_ids`` that have a current voice profile (for ``profiles.hooks``)."""
    return set(
        VoiceProfile.objects.filter(
            profile_id__in=list(profile_ids), is_current=True
        ).values_list("profile_id", flat=True)
    )
