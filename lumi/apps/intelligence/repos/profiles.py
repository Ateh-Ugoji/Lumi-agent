"""Stores over ARCHITECT's services (``apps.profiles``, ``apps.chat``) plus the niche and peer posts.

Everything that has a service function calls it; nothing here re-implements their SQL.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from django.db import transaction

from apps.chat import services as chat_services
from apps.intelligence.models import (
    NichePreference,
    NichePreferenceHandle,
    NichePreferenceKeyword,
    NicheReport,
    NicheReportPeer,
    NicheSource,
)
from apps.intelligence.repos.aio import aio
from apps.profiles import services
from apps.profiles.models import HandleOrigin, Post, SocialProfile
from lumi_ai.ports import (
    ActivityOut,
    AlertOut,
    BaselineOut,
    ChatMessageIn,
    ChatMessageOut,
    ListeningConfig,
    NicheIn,
    NicheOut,
    PeerPostIn,
    PeerPostOut,
    PostKind,
    PostMetrics,
    PostOut,
    ProfileInfo,
    RankedPostOut,
)

logger = logging.getLogger(__name__)


class ProfileRepo:
    """``ProfileStore``: the profile comes from ARCHITECT, the niche is ours."""

    @aio
    def get_profile(self, profile_id: int) -> ProfileInfo | None:
        return services.get_profile(profile_id)

    @aio
    def get_niche(self, profile_id: int) -> NicheOut | None:
        row = NichePreference.objects.filter(
            profile_id=profile_id, is_active=True
        ).first()
        return _niche_out(row) if row else None

    @aio
    def save_niche(self, profile_id: int, niche: NicheIn) -> NicheOut:
        """Make ``niche`` the profile's one active niche (the DB allows a single active row)."""
        keywords = _dedupe_ci(niche.keywords)
        with transaction.atomic():
            NichePreference.objects.filter(
                profile_id=profile_id, is_active=True
            ).exclude(niche_key=niche.niche_key).update(is_active=False)
            row, _ = NichePreference.objects.update_or_create(
                profile_id=profile_id,
                niche_key=niche.niche_key,
                defaults={
                    "title": niche.title,
                    "source": NicheSource(niche.source),
                    "is_active": True,
                },
            )
            row.keywords.all().delete()
            NichePreferenceKeyword.objects.bulk_create(
                [NichePreferenceKeyword(preference=row, keyword=k) for k in keywords]
            )
            row.handles.all().delete()
            handle_ids: dict[int, None] = {}
            for platform, names in niche.tracked_handles.items():
                for name in names:
                    handle_ids[
                        services.get_or_create_handle(
                            str(platform), name, origin=HandleOrigin.NICHE
                        )
                    ] = None
            NichePreferenceHandle.objects.bulk_create(
                [NichePreferenceHandle(preference=row, handle_id=h) for h in handle_ids]
            )
            row.refresh_from_db()
        return _niche_out(row)


def _dedupe_ci(values: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        clean = " ".join(value.split())
        if clean:
            seen.setdefault(clean.lower(), clean)
    return list(seen.values())


def _niche_out(row: NichePreference) -> NicheOut:
    handles: dict[str, list[str]] = {}
    for link in row.handles.select_related("handle").order_by("id"):
        handles.setdefault(link.handle.platform, []).append(
            link.handle.handle_normalized
        )
    return NicheOut(
        profile_id=row.profile_id,
        niche_key=row.niche_key,
        title=row.title,
        keywords=tuple(row.keywords.order_by("id").values_list("keyword", flat=True)),
        tracked_handles={p: tuple(h) for p, h in handles.items()},  # type: ignore[misc]
        source=row.source,  # type: ignore[arg-type]
        updated_at=row.updated_at,
    )


class PostRepo:
    """``PostStore`` straight over ``apps.profiles.services``."""

    @aio
    def list_posts(
        self,
        profile_id: int,
        *,
        platform: str | None = None,
        kinds: Sequence[PostKind] | None = None,
        since: datetime | None = None,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> list[PostOut]:
        return services.list_posts(
            profile_id,
            platform=platform,
            kinds=kinds,
            since=since,
            limit=limit,
            include_deleted=include_deleted,
        )

    @aio
    def rank_posts(
        self,
        profile_id: int,
        *,
        metric: str = "views",
        platform: str | None = None,
        since: datetime | None = None,
        limit: int = 5,
    ) -> list[RankedPostOut]:
        return services.rank_posts(
            profile_id, metric=metric, platform=platform, since=since, limit=limit
        )

    @aio
    def get_posts(self, post_ids: Sequence[int]) -> list[PostOut]:
        return services.get_posts(post_ids)

    @aio
    def list_activity(
        self, profile_id: int, *, kind: str | None = None, limit: int = 50
    ) -> list[ActivityOut]:
        return services.list_activity(profile_id, kind=kind, limit=limit)

    @aio
    def get_baseline(self, profile_id: int) -> BaselineOut | None:
        return services.latest_baseline(profile_id)

    @aio
    def save_baseline(self, baseline: BaselineOut) -> None:
        services.save_baseline(baseline)


class PeerPostRepo:
    """``PeerPostStore``: other accounts' posts live in ``posts`` under their own handle.

    ``niche_key`` has no column on ``posts``: the niche of a peer post is derived from who wrote it
    (a handle of the niche or of one of the profile's reports), so ``PeerPostOut.niche_key`` is
    ``None`` and ``list_peer_posts(niche_key=...)`` filters by those handles.
    """

    @aio
    def save_peer_posts(
        self, profile_id: int, posts: Sequence[PeerPostIn]
    ) -> list[PeerPostOut]:
        by_handle: dict[tuple[str, str], list[PeerPostIn]] = {}
        for post in posts:
            by_handle.setdefault((str(post.platform), post.author_handle), []).append(
                post
            )
        ids: dict[int, None] = {}
        with transaction.atomic():
            for (platform, author), group in by_handle.items():
                # fill-only: a photo already on the handle (from the handle search) is kept
                avatar = next(
                    (p.author_avatar_url for p in group if p.author_avatar_url), ""
                )
                handle_id = services.get_or_create_handle(
                    platform, author, origin=HandleOrigin.NICHE, avatar_url=avatar
                )
                result = services.upsert_posts(handle_id, group)
                ids.update(dict.fromkeys(result.post_ids))
        return _peer_outs(
            services.get_posts(list(ids), profile_id=profile_id), profile_id
        )

    @aio
    def get_peer_posts(self, ids: Sequence[int]) -> list[PeerPostOut]:
        return _peer_outs(services.get_posts(ids), 0)

    @aio
    def list_peer_posts(
        self, profile_id: int, *, niche_key: str | None = None, limit: int = 200
    ) -> list[PeerPostOut]:
        niches = NichePreference.objects.filter(profile_id=profile_id)
        reports = NicheReport.objects.filter(profile_id=profile_id)
        if niche_key is not None:
            niches = niches.filter(niche_key=niche_key)
            reports = reports.filter(niche=niche_key)
        authors = set(
            NichePreferenceHandle.objects.filter(preference__in=niches).values_list(
                "handle_id", flat=True
            )
        ) | set(
            NicheReportPeer.objects.filter(report__in=reports).values_list(
                "handle_id", flat=True
            )
        )
        own = SocialProfile.objects.filter(pk=profile_id).values_list(
            "handle_id", flat=True
        )
        authors -= set(own)
        if not authors:
            return []
        ids = list(
            Post.objects.filter(author_id__in=authors, is_stub=False)
            .order_by("-published_at", "-id")
            .values_list("pk", flat=True)[: max(limit, 0)]
        )
        return _peer_outs(services.get_posts(ids, profile_id=profile_id), profile_id)


def _peer_outs(posts: Sequence[PostOut], profile_id: int) -> list[PeerPostOut]:
    avatars = dict(
        Post.objects.filter(pk__in=[p.id for p in posts]).values_list(
            "pk", "author__avatar_url"
        )
    )
    return [
        PeerPostOut(
            id=p.id,
            profile_id=profile_id,
            platform=p.platform,
            external_id=p.external_id,
            author_handle=p.author_handle or "",
            text=p.text,
            published_at=p.published_at,
            url=p.url,
            metrics=p.metrics or PostMetrics(),
            media=p.media,
            niche_key=None,
            author_avatar_url=avatars.get(p.id) or "",
        )
        for p in posts
    ]


class ListeningRepo:
    """``ListeningStore`` over ``apps.profiles.services``."""

    @aio
    def unread_alerts(self, profile_id: int) -> list[AlertOut]:
        return services.unread_alerts(profile_id)

    @aio
    def dismiss_alert(self, profile_id: int, alert_id: int) -> bool:
        return services.dismiss_alert(profile_id, alert_id)

    @aio
    def get_listening(self, profile_id: int) -> ListeningConfig:
        return services.get_listening(profile_id)

    @aio
    def set_listening(self, config: ListeningConfig) -> ListeningConfig:
        return services.set_listening(config)


class MatchRepo:
    """``MatchStore`` (ports 1.6)."""

    @aio
    def record_listening_match(
        self, profile_id: int, post_id: int, score: float | None = None
    ) -> bool:
        return services.record_listening_match(profile_id, post_id, score)


class ChatRepo:
    """``ChatStore`` over ``apps.chat.services``."""

    @aio
    def history(self, profile_id: int, limit: int) -> list[ChatMessageOut]:
        return chat_services.history(profile_id, limit)

    @aio
    def append(self, profile_id: int, message: ChatMessageIn) -> int:
        return chat_services.append_message(profile_id, message)


__all__ = [
    "ChatRepo",
    "ListeningRepo",
    "MatchRepo",
    "PeerPostRepo",
    "PostRepo",
    "ProfileRepo",
]
