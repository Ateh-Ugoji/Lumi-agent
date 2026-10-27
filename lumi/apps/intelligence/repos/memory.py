"""``MemoryStore``: short facts about the user and one running summary. Vectors live in Chroma."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.intelligence.models import MemoryNote, ProfileMemorySummary
from apps.intelligence.repos.aio import aio
from lumi_ai.ports import MemoryNoteOut


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


def _out(row: MemoryNote) -> MemoryNoteOut:
    return MemoryNoteOut(
        id=row.pk,
        profile_id=row.profile_id,
        text=row.content,
        kind=row.kind,
        created_at=row.created_at,
    )


class MemoryRepo:
    @aio
    def add_note(
        self, profile_id: int, text: str, kind: str = "fact"
    ) -> tuple[MemoryNoteOut, bool]:
        """Store a note; the same text (ignoring case and spacing) is stored once."""
        row, created = MemoryNote.objects.get_or_create(
            profile_id=profile_id,
            content_hash=_hash(text),
            defaults={"content": text, "kind": kind},
        )
        return _out(row), created

    @aio
    def get_notes(self, ids: Sequence[int]) -> list[MemoryNoteOut]:
        by_id = {n.pk: n for n in MemoryNote.objects.filter(pk__in=list(ids))}
        return [_out(by_id[i]) for i in ids if i in by_id]

    @aio
    def touch_notes(self, ids: Sequence[int]) -> None:
        MemoryNote.objects.filter(pk__in=list(ids)).update(
            last_accessed_at=timezone.now(), access_count=F("access_count") + 1
        )

    @aio
    def list_notes(self, profile_id: int, *, limit: int = 100) -> list[MemoryNoteOut]:
        rows = MemoryNote.objects.filter(profile_id=profile_id).order_by("-id")
        return [_out(r) for r in rows[: max(limit, 0)]]

    @aio
    def delete_notes_older_than(self, profile_id: int, cutoff: datetime) -> list[int]:
        """Delete notes not read since ``cutoff`` and return their ids (to drop their vectors)."""
        with transaction.atomic():
            stale = list(
                MemoryNote.objects.select_for_update()
                .filter(profile_id=profile_id, last_accessed_at__lt=cutoff)
                .values_list("pk", flat=True)
            )
            MemoryNote.objects.filter(pk__in=stale).delete()
        return stale

    @aio
    def get_summary(self, profile_id: int) -> str:
        row = ProfileMemorySummary.objects.filter(profile_id=profile_id).first()
        return row.summary_md if row else ""

    @aio
    def set_summary(self, profile_id: int, text: str) -> None:
        ProfileMemorySummary.objects.update_or_create(
            profile_id=profile_id, defaults={"summary_md": text}
        )
