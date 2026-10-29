"""``ReportStore``: niche/framework reports, their frameworks and the per-post taggings."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.intelligence.models import (
    Framework,
    FrameworkEvidence,
    NicheReport,
    NicheReportPeer,
    PostTagging,
    ReportOrigin,
    ReportStatus,
    TaggingStatus,
)
from apps.intelligence.repos.aio import aio
from apps.profiles import services
from apps.profiles.models import HandleOrigin, Post
from lumi_ai.ports import (
    FrameworkIn,
    FrameworkOut,
    NicheReportIn,
    NicheReportOut,
    TaggingRecord,
)

logger = logging.getLogger(__name__)

#: ``niche_reports`` has no column for the honest reason a report is not ``ok``: it rides in the
#: raw JSON next to the validated payload and is peeled off again when the report is read.
DETAIL_KEY = "_detail"


def _split_ref(ref: str) -> tuple[str, str]:
    platform, _, external_id = ref.partition(":")
    return platform, external_id


def _resolve_refs(refs: Sequence[str]) -> dict[str, Post]:
    """``"<platform>:<external_id>"`` -> stored post (the lowest id when two authors collide)."""
    wanted = {r: _split_ref(r) for r in refs if ":" in r}
    if not wanted:
        return {}
    query = Q()
    for platform, external_id in set(wanted.values()):
        query |= Q(author__platform=platform, platform_post_id=external_id)
    found: dict[tuple[str, str], Post] = {}
    for post in Post.objects.filter(query).select_related("author").order_by("-id"):
        found[(post.author.platform, post.platform_post_id)] = post
    return {ref: found[key] for ref, key in wanted.items() if key in found}


def _ref(post: Post) -> str:
    return f"{post.author.platform}:{post.platform_post_id}"


def _framework_out(row: Framework, profile_id: int) -> FrameworkOut:
    payload = dict(row.payload or {})
    refs = tuple(
        _ref(e.post) for e in row.evidence.select_related("post__author").order_by("id")
    )
    return FrameworkOut(
        id=row.pk,
        profile_id=profile_id,
        report_id=row.report_id,
        name=str(payload.get("key") or row.name),
        title=row.name,
        description=row.description,
        evidence_post_refs=refs,
        lift=row.lift,
        confidence=row.confidence,
        payload=payload,
    )


def _report_out(row: NicheReport) -> NicheReportOut:
    payload = dict(row.report or {})
    detail = payload.pop(DETAIL_KEY, None)
    frameworks = tuple(
        _framework_out(f, row.profile_id) for f in row.frameworks.order_by("ordinal")
    )
    return NicheReportOut(
        id=row.pk,
        profile_id=row.profile_id,
        niche_key=row.niche or None,
        status=row.status,  # type: ignore[arg-type]
        posts_analyzed=row.posts_analyzed,
        winner_count=row.winner_count,
        payload=payload,
        frameworks=frameworks,
        detail=detail,
        created_at=row.created_at,
        query=row.query,
        peers_analyzed=row.peers_analyzed,
    )


class ReportRepo:
    @aio
    def save_report(self, profile_id: int, report: NicheReportIn) -> NicheReportOut:
        raw: dict[str, Any] = dict(report.payload)
        if report.detail:
            raw[DETAIL_KEY] = report.detail
        with transaction.atomic():
            row = NicheReport.objects.create(
                profile_id=profile_id,
                query=report.query,
                niche=report.niche_key or "",
                status=ReportStatus(report.status),
                posts_analyzed=report.posts_analyzed,
                winner_count=report.winner_count,
                peers_analyzed=report.peers_analyzed,
                report=raw,
                origin=ReportOrigin.PIPELINE,
            )
            handle_ids: dict[int, None] = {}
            for platform, names in report.peer_handles.items():
                for name in names:
                    handle_ids[
                        services.get_or_create_handle(
                            str(platform), name, origin=HandleOrigin.NICHE
                        )
                    ] = None
            NicheReportPeer.objects.bulk_create(
                [NicheReportPeer(report=row, handle_id=h) for h in handle_ids]
            )
            self._save_frameworks(row, report.frameworks)
        return _report_out(row)

    @staticmethod
    def _save_frameworks(row: NicheReport, frameworks: Sequence[FrameworkIn]) -> None:
        posts = _resolve_refs([r for f in frameworks for r in f.evidence_post_refs])
        for ordinal, fw in enumerate(frameworks):
            payload = {**fw.payload, "key": fw.name}
            made = Framework.objects.create(
                report=row,
                name=fw.title,
                description=fw.description,
                lift=fw.lift,
                confidence=fw.confidence,
                payload=payload,
                ordinal=ordinal,
            )
            linked: dict[int, None] = {}
            for ref in fw.evidence_post_refs:
                post = posts.get(ref)
                if post is None:
                    logger.warning(
                        "framework %r cites %s, which is not stored", fw.name, ref
                    )
                    continue
                linked[post.pk] = None
            FrameworkEvidence.objects.bulk_create(
                [FrameworkEvidence(framework=made, post_id=p) for p in linked]
            )

    @aio
    def latest_report(self, profile_id: int) -> NicheReportOut | None:
        row = (
            NicheReport.objects.filter(profile_id=profile_id)
            .order_by("-created_at", "-id")
            .first()
        )
        return _report_out(row) if row else None

    @aio
    def get_frameworks(self, ids: Sequence[int]) -> list[FrameworkOut]:
        rows = {
            f.pk: f
            for f in Framework.objects.filter(pk__in=list(ids)).select_related("report")
        }
        return [
            _framework_out(rows[i], rows[i].report.profile_id) for i in ids if i in rows
        ]

    @aio
    def list_frameworks(
        self, profile_id: int, *, limit: int = 100
    ) -> list[FrameworkOut]:
        rows = (
            Framework.objects.filter(report__profile_id=profile_id)
            .select_related("report")
            .order_by("-report__created_at", "-report_id", "ordinal")[: max(limit, 0)]
        )
        return [_framework_out(f, profile_id) for f in rows]

    @aio
    def save_taggings(self, profile_id: int, taggings: Sequence[TaggingRecord]) -> int:
        """Upsert one row per (post, prompt_version); return how many were written."""
        posts = _resolve_refs([t.post_ref for t in taggings])
        written = 0
        now = timezone.now()
        with transaction.atomic():
            for tagging in taggings:
                post = posts.get(tagging.post_ref)
                if post is None:
                    logger.warning(
                        "tagging for %s skipped: post not stored", tagging.post_ref
                    )
                    continue
                PostTagging.objects.update_or_create(
                    post=post,
                    prompt_version=tagging.prompt_version,
                    defaults={
                        "status": TaggingStatus(tagging.status),
                        "analysis": dict(tagging.analysis)
                        if tagging.analysis
                        else None,
                        "framework_guess": tagging.framework_guess or "",
                        "validation_error": tagging.validation_error or "",
                        "tagged_at": now,
                    },
                )
                written += 1
        return written

    @aio
    def cached_taggings(
        self, profile_id: int, post_refs: Sequence[str], prompt_version: str
    ) -> list[TaggingRecord]:
        posts = _resolve_refs(post_refs)
        by_post = {p.pk: ref for ref, p in posts.items()}
        rows = PostTagging.objects.filter(
            post_id__in=list(by_post), prompt_version=prompt_version
        ).select_related("post__author")
        return [
            TaggingRecord(
                post_ref=by_post[r.post_id],
                handle=r.post.author.handle_normalized,
                prompt_version=r.prompt_version,
                status=r.status,  # type: ignore[arg-type]
                analysis=r.analysis,
                framework_guess=r.framework_guess or None,
                validation_error=r.validation_error or None,
            )
            for r in rows
            if r.status in (TaggingStatus.OK, TaggingStatus.FAILED)
        ]
