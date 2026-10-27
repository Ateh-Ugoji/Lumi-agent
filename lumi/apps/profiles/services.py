"""Profile, handle, post, alert and listening services. See docs/CONTRATOS.md section 5.

Everything returns the dataclasses of ``lumi_ai.ports`` or a ``TypedDict``, never an ORM
instance. Services do not check permissions (the view does with ``IsProfileOwner``); the ones
that take ``user_id`` filter by it. Each function has an async twin named ``a<name>``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from asgiref.sync import sync_to_async
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.choices import Platform, PostKind
from apps.profiles import hooks
from apps.profiles.models import (
    HANDLE_RE,
    Alert,
    AlertStatus,
    HandleOrigin,
    HandleSnapshot,
    ListeningKeyword,
    MetricSnapshot,
    PollConfig,
    Post,
    PostMedia,
    ProfileBaseline,
    SocialHandle,
    SocialProfile,
)
from lumi_ai.ports import (
    ActivityOut,
    AlertOut,
    BaselineOut,
    ListeningConfig,
    MediaRef,
    PeerPostIn,
    PostIn,
    PostMetrics,
    PostOut,
    ProfileInfo,
)

__all__ = [
    "AlertDetail",
    "InvalidHandle",
    "ProfileSummary",
    "SnapshotIn",
    "UpsertResult",
]

METRIC_FIELDS = ("likes", "comments", "shares", "views", "bookmarks", "quotes")
X_HANDLE_MAX = 15
KEYWORD_MAX = 100
MIN_INTERVAL, MAX_INTERVAL = 1, 1440
DEFAULT_INTERVAL = 5

# ``add-if-absent``: a write never lowers the origin of an existing handle.
_ORIGIN_RANK = {
    HandleOrigin.IMPORT: 0,
    HandleOrigin.NICHE: 1,
    HandleOrigin.CACHE: 2,
    HandleOrigin.LIVE: 3,
    HandleOrigin.SELECTED: 4,
    HandleOrigin.PROFILE: 5,
}


class InvalidHandle(ValueError):
    """The text is not a valid handle for the platform."""


class ProfileSummary(TypedDict):
    id: int
    name: str
    platform: str
    handle: str
    has_voice_profile: bool
    listening_active: bool
    timezone: str | None
    timezone_source: str | None


class AlertDetail(TypedDict):
    id: int
    post_id: int
    caption: str
    platform_post_id: str
    alerted_at: datetime
    kind: str
    velocity: float | None
    baseline_velocity: float | None


@dataclass(frozen=True, slots=True)
class UpsertResult:
    inserted: int
    updated: int
    post_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SnapshotIn:
    """One metric reading to append to a post."""

    captured_at: datetime
    metrics: PostMetrics
    source: str | None = None


# --------------------------------------------------------------------------- handles


def normalize_handle(platform: str, handle: str) -> str:
    """Lowercase, no ``@``; raise :class:`InvalidHandle` when the platform would refuse it."""
    if platform not in Platform.values:
        raise InvalidHandle(f"unknown platform {platform!r}")
    cleaned = (handle or "").strip().lstrip("@").strip().lower()
    if not re.fullmatch(HANDLE_RE[1:-1], cleaned):
        raise InvalidHandle(f"invalid handle {handle!r}")
    if platform == Platform.X and len(cleaned) > X_HANDLE_MAX:
        raise InvalidHandle(f"an X handle has at most {X_HANDLE_MAX} characters")
    return cleaned


def record_handle_snapshot(
    handle_id: int,
    *,
    followers: int | None,
    following: int | None = None,
    source: str | None = None,
    captured_at: datetime | None = None,
) -> None:
    """Append a follower reading and refresh the denormalized copy on the handle."""
    when = captured_at or timezone.now()
    with transaction.atomic():
        HandleSnapshot.objects.bulk_create(
            [
                HandleSnapshot(
                    handle_id=handle_id,
                    captured_at=when,
                    followers=followers,
                    following=following,
                    source=source,
                )
            ],
            ignore_conflicts=True,
        )
        if followers is not None:
            SocialHandle.objects.filter(pk=handle_id).filter(
                Q(follower_count_at__isnull=True) | Q(follower_count_at__lte=when)
            ).update(follower_count=followers, follower_count_at=when)


def get_or_create_handle(
    platform: str,
    handle: str,
    *,
    origin: str = HandleOrigin.LIVE,
    display_name: str = "",
    avatar_url: str = "",
    external_id: str = "",
    follower_count: int | None = None,
    following_count: int | None = None,
    source: str | None = None,
    handle_display: str = "",
) -> int:
    """Return ``social_handles.id``. Never lowers the origin; only fills empty fields."""
    normalized = normalize_handle(platform, handle)
    origin = HandleOrigin(origin)
    now = timezone.now()
    display = handle_display or (handle or "").strip().lstrip("@")[:100]
    with transaction.atomic():
        row, created = SocialHandle.objects.select_for_update().get_or_create(
            platform=platform,
            handle_normalized=normalized,
            defaults={
                "handle_display": display,
                "display_name": display_name,
                "avatar_url": avatar_url,
                "external_id": external_id,
                "origin": origin,
            },
        )
        if not created:
            changed: list[str] = []
            if _ORIGIN_RANK[origin] > _ORIGIN_RANK[HandleOrigin(row.origin)]:
                row.origin = origin
                changed.append("origin")
            for name, value in (
                ("handle_display", display if handle_display else ""),
                ("display_name", display_name),
                ("avatar_url", avatar_url),
                ("external_id", external_id),
            ):
                if value and not getattr(row, name):
                    setattr(row, name, value)
                    changed.append(name)
            if (now - row.last_seen_at).total_seconds() > 3600:
                row.last_seen_at = now
                changed.append("last_seen_at")
            if changed:
                row.save(update_fields=[*changed, "updated_at"])
        if follower_count is not None:
            record_handle_snapshot(
                row.pk,
                followers=follower_count,
                following=following_count,
                source=source,
                captured_at=now,
            )
    return row.pk


# --------------------------------------------------------------------------- profiles


def _display_name(handle: SocialHandle) -> str:
    return handle.display_name or handle.handle_display or handle.handle_normalized


def _infos(profiles: Sequence[SocialProfile]) -> list[ProfileInfo]:
    connected = hooks.connected_platforms_reader([p.pk for p in profiles])
    return [
        ProfileInfo(
            id=p.pk,
            name=_display_name(p.handle),
            handle=p.handle.handle_normalized,
            primary_platform=p.handle.platform,
            connected_platforms=connected.get(p.pk, ()),
            timezone=p.timezone,
        )
        for p in profiles
    ]


def get_profile(profile_id: int, user_id: int | None = None) -> ProfileInfo | None:
    queryset = SocialProfile.objects.select_related("handle").filter(pk=profile_id)
    if user_id is not None:
        queryset = queryset.filter(user_id=user_id)
    profile = queryset.first()
    return _infos([profile])[0] if profile else None


def list_profiles(user_id: int) -> list[ProfileInfo]:
    profiles = list(
        SocialProfile.objects.select_related("handle")
        .filter(user_id=user_id)
        .order_by("id")
    )
    return _infos(profiles)


def _summaries(profiles: Sequence[SocialProfile]) -> list[ProfileSummary]:
    ids = [p.pk for p in profiles]
    voiced = hooks.voice_profile_reader(ids)
    listening = set(
        PollConfig.objects.filter(profile_id__in=ids, is_active=True).values_list(
            "profile_id", flat=True
        )
    )
    return [
        ProfileSummary(
            id=p.pk,
            name=_display_name(p.handle),
            platform=p.handle.platform,
            handle=p.handle.handle_display or p.handle.handle_normalized,
            has_voice_profile=p.pk in voiced,
            listening_active=p.pk in listening,
            timezone=p.timezone,
            timezone_source=p.timezone_source,
        )
        for p in profiles
    ]


def list_profile_summaries(user_id: int) -> list[ProfileSummary]:
    profiles = list(
        SocialProfile.objects.select_related("handle")
        .filter(user_id=user_id)
        .order_by("id")
    )
    return _summaries(profiles)


def get_profile_summary(profile_id: int) -> ProfileSummary | None:
    profile = (
        SocialProfile.objects.select_related("handle").filter(pk=profile_id).first()
    )
    return _summaries([profile])[0] if profile else None


def select_info(profile_id: int) -> dict[str, Any] | None:
    """Body of ``POST /profiles/{id}/select``."""
    summary = get_profile_summary(profile_id)
    if summary is None:
        return None
    handle_id = SocialProfile.objects.values_list("handle_id", flat=True).get(
        pk=profile_id
    )
    count = Post.objects.filter(
        author_id=handle_id, kind=PostKind.ORIGINAL, is_deleted_suspect=False
    ).count()
    return {
        "profile_id": profile_id,
        "name": summary["name"],
        "voice_profile_exists": summary["has_voice_profile"],
        "post_count": count,
        "listening_active": summary["listening_active"],
    }


def get_or_create_profile(user_id: int, platform: str, handle: str) -> tuple[int, bool]:
    """Return ``(profile_id, created)`` for the user's account on a network."""
    handle_id = get_or_create_handle(platform, handle, origin=HandleOrigin.PROFILE)
    profile, created = SocialProfile.objects.get_or_create(
        user_id=user_id, handle_id=handle_id
    )
    return profile.pk, created


def mark_bootstrapped(profile_id: int) -> bool:
    """``True`` only the first time. One conditional UPDATE, safe across processes."""
    return bool(
        SocialProfile.objects.filter(
            pk=profile_id, bootstrapped_at__isnull=True
        ).update(bootstrapped_at=timezone.now())
    )


# --------------------------------------------------------------------------- posts


def _handle_ids(profile_id: int) -> tuple[int, str] | None:
    row = (
        SocialProfile.objects.filter(pk=profile_id)
        .values_list("handle_id", "handle__platform")
        .first()
    )
    return row


def _latest_snapshots(post_ids: Sequence[int]) -> dict[int, MetricSnapshot]:
    if not post_ids:
        return {}
    rows = (
        MetricSnapshot.objects.filter(post_id__in=post_ids)
        .order_by("post_id", "-captured_at")
        .distinct("post_id")
    )
    return {row.post_id: row for row in rows}


def _to_post_out(
    post: Post,
    profile_id: int,
    snapshot: MetricSnapshot | None,
    now: datetime,
) -> PostOut:
    metrics = (
        PostMetrics(
            **{name: getattr(snapshot, name) for name in ("views", *METRIC_FIELDS)}
        )
        if snapshot
        else None
    )
    age = (
        (snapshot.captured_at - post.published_at).total_seconds() / 3600
        if snapshot and post.published_at
        else None
    )
    return PostOut(
        id=post.pk,
        profile_id=profile_id,
        platform=post.author.platform,
        external_id=post.platform_post_id,
        text=post.caption,
        published_at=post.published_at or post.created_at,
        kind=post.kind,
        url=post.url or None,
        author_handle=post.author.handle_normalized,
        metrics=metrics,
        metrics_age_hours=age,
        media=tuple(MediaRef(kind=m.kind, url=m.url) for m in post.media.all()),
        is_deleted_suspect=post.is_deleted_suspect,
        text_truncated=post.text_truncated,
    )


def _post_outs(posts: Sequence[Post], profile_ids: Mapping[int, int]) -> list[PostOut]:
    snapshots = _latest_snapshots([p.pk for p in posts])
    now = timezone.now()
    return [
        _to_post_out(p, profile_ids.get(p.author_id, 0), snapshots.get(p.pk), now)
        for p in posts
    ]


def _posts_queryset():
    return Post.objects.select_related("author").prefetch_related("media")


def list_posts(
    profile_id: int,
    *,
    platform: str | None = None,
    kinds: Iterable[str] | None = None,
    since: datetime | None = None,
    limit: int = 50,
    include_deleted: bool = False,
) -> list[PostOut]:
    """Own posts, newest first. ``kinds=None`` means originals only."""
    found = _handle_ids(profile_id)
    if found is None or (platform is not None and platform != found[1]):
        return []
    queryset = _posts_queryset().filter(
        author_id=found[0],
        is_stub=False,
        kind__in=list(kinds) if kinds else [PostKind.ORIGINAL],
    )
    if not include_deleted:
        queryset = queryset.filter(is_deleted_suspect=False)
    if since is not None:
        queryset = queryset.filter(published_at__gte=since)
    posts = list(queryset.order_by("-published_at", "-id")[: max(limit, 0)])
    return _post_outs(posts, {found[0]: profile_id})


def get_posts(
    post_ids: Sequence[int], *, profile_id: int | None = None
) -> list[PostOut]:
    """Posts by id, in the order asked. Ids that do not exist are skipped.

    ``profile_id`` labels the result. Without it the label is the lowest profile id whose handle
    wrote the post, or ``0`` for a post nobody owns (a competitor's).
    """
    if not post_ids:
        return []
    by_id = {p.pk: p for p in _posts_queryset().filter(pk__in=list(post_ids))}
    posts = [by_id[i] for i in post_ids if i in by_id]
    if profile_id is not None:
        labels = {p.author_id: profile_id for p in posts}
    else:
        owners = (
            SocialProfile.objects.filter(handle_id__in={p.author_id for p in posts})
            .order_by("-id")
            .values_list("handle_id", "id")
        )
        labels = dict(owners)  # the last write per handle is the lowest id
    return _post_outs(posts, labels)


def list_activity(
    profile_id: int, *, kind: str | None = None, limit: int = 50
) -> list[ActivityOut]:
    """Own replies and retweets, newest first."""
    found = _handle_ids(profile_id)
    if found is None:
        return []
    kinds = [kind] if kind else [PostKind.REPLY, PostKind.RETWEET]
    rows = (
        Post.objects.filter(author_id=found[0], is_stub=False, kind__in=kinds)
        .exclude(kind=PostKind.ORIGINAL)
        .order_by("-published_at", "-id")[: max(limit, 0)]
    )
    return [
        ActivityOut(
            id=p.pk,
            profile_id=profile_id,
            platform=found[1],
            kind=p.kind,
            text=p.caption,
            published_at=p.published_at or p.created_at,
        )
        for p in rows
    ]


_UPSERT_SQL = """
INSERT INTO posts (author_id, platform_post_id, kind, kind_source, caption, url, published_at,
                   is_stub, source, conversation_id, language, text_truncated,
                   is_deleted_suspect, last_seen_at, created_at, updated_at)
VALUES {values}
ON CONFLICT (author_id, platform_post_id) DO UPDATE SET
    kind_source = COALESCE(EXCLUDED.kind_source, posts.kind_source),
    caption = CASE WHEN EXCLUDED.caption <> '' THEN EXCLUDED.caption ELSE posts.caption END,
    url = CASE WHEN EXCLUDED.url <> '' THEN EXCLUDED.url ELSE posts.url END,
    published_at = COALESCE(EXCLUDED.published_at, posts.published_at),
    is_stub = false,
    source = COALESCE(EXCLUDED.source, posts.source),
    conversation_id = CASE WHEN EXCLUDED.conversation_id <> '' THEN EXCLUDED.conversation_id
                           ELSE posts.conversation_id END,
    language = CASE WHEN EXCLUDED.language <> '' THEN EXCLUDED.language ELSE posts.language END,
    text_truncated = EXCLUDED.text_truncated,
    is_deleted_suspect = false,
    last_seen_at = EXCLUDED.last_seen_at,
    updated_at = EXCLUDED.updated_at
RETURNING id, platform_post_id, (xmax = 0) AS inserted
"""


def _metric_values(metrics: PostMetrics) -> dict[str, int | None]:
    return {name: getattr(metrics, name) for name in ("views", *METRIC_FIELDS)}


def _as_row(
    post: PostIn | PeerPostIn, handle_id: int, now: datetime
) -> tuple[Any, ...]:
    kind = getattr(post, "kind", None)
    return (
        handle_id,
        post.external_id,
        kind,
        None,
        post.text or "",
        post.url or "",
        post.published_at,
        False,
        getattr(post, "source", None),
        getattr(post, "conversation_id", None) or "",
        getattr(post, "language", None) or "",
        bool(getattr(post, "text_truncated", False)),
        False,
        now,
        now,
        now,
    )


def upsert_posts(handle_id: int, posts: Sequence[PostIn | PeerPostIn]) -> UpsertResult:
    """Insert or update posts of one author in a single ``INSERT ... ON CONFLICT``.

    Idempotent. A ``NULL`` never overwrites a known ``published_at``, kind, source or metric.
    A metric snapshot is written only when the (carried-forward) metrics changed.
    """
    unique: dict[str, PostIn | PeerPostIn] = {}
    for post in posts:
        unique[post.external_id] = post  # the last repeat in a batch wins
    if not unique:
        return UpsertResult(0, 0, ())
    now = timezone.now()
    rows = [_as_row(p, handle_id, now) for p in unique.values()]
    placeholder = (
        "(%s, %s, COALESCE(%s::text, 'original'), " + ", ".join(["%s"] * 13) + ")"
    )
    statement = _UPSERT_SQL.format(values=", ".join([placeholder] * len(rows)))

    with transaction.atomic(), connection.cursor() as cursor:
        flat: list[Any] = [value for row in rows for value in row]
        cursor.execute(statement, flat)
        returned = cursor.fetchall()
        ids = {external: (pk, inserted) for pk, external, inserted in returned}
        # A classified kind may still correct a stored one: do it for the posts that came typed.
        typed = {
            ids[external][0]: post.kind
            for external, post in unique.items()
            if getattr(post, "kind", None)
        }
        for kind in set(typed.values()):
            Post.objects.filter(
                pk__in=[pk for pk, k in typed.items() if k == kind]
            ).exclude(kind=kind).update(kind=kind)
        _write_media(unique, ids)
        _write_snapshots(unique, ids, now)
    inserted = sum(1 for _, was_new in ids.values() if was_new)
    return UpsertResult(
        inserted=inserted,
        updated=len(ids) - inserted,
        post_ids=tuple(ids[external][0] for external in unique),
    )


def _write_media(
    posts: Mapping[str, PostIn | PeerPostIn], ids: Mapping[str, tuple[int, bool]]
) -> None:
    media: list[PostMedia] = []
    for external, post in posts.items():
        for position, ref in enumerate(post.media or ()):
            media.append(
                PostMedia(
                    post_id=ids[external][0],
                    position=position,
                    kind=ref.kind,
                    url=ref.url,
                )
            )
    if media:
        PostMedia.objects.bulk_create(
            media,
            update_conflicts=True,
            unique_fields=["post", "position"],
            update_fields=["kind", "url"],
        )


def _write_snapshots(
    posts: Mapping[str, PostIn | PeerPostIn],
    ids: Mapping[str, tuple[int, bool]],
    now: datetime,
) -> None:
    incoming = {
        ids[external][0]: (post.metrics, getattr(post, "source", None))
        for external, post in posts.items()
        if post.metrics is not None
        and any(v is not None for v in _metric_values(post.metrics).values())
    }
    if not incoming:
        return
    latest = _latest_snapshots(list(incoming))
    fresh: list[MetricSnapshot] = []
    for post_id, (metrics, source) in incoming.items():
        previous = latest.get(post_id)
        merged = {
            name: value
            if value is not None
            else (getattr(previous, name) if previous else None)
            for name, value in _metric_values(metrics).items()
        }
        if previous and all(
            getattr(previous, name) == value for name, value in merged.items()
        ):
            continue
        fresh.append(
            MetricSnapshot(post_id=post_id, captured_at=now, source=source, **merged)
        )
    if fresh:
        MetricSnapshot.objects.bulk_create(fresh, ignore_conflicts=True)


def append_metric_snapshots(post_id: int, snapshots: Sequence[SnapshotIn]) -> int:
    """Insert readings. A repeat of (post, captured_at) is ignored. Returns rows offered."""
    rows = [
        MetricSnapshot(
            post_id=post_id,
            captured_at=s.captured_at,
            source=s.source,
            **_metric_values(s.metrics),
        )
        for s in snapshots
    ]
    MetricSnapshot.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


# --------------------------------------------------------------------------- baseline


def latest_baseline(profile_id: int) -> BaselineOut | None:
    row = (
        ProfileBaseline.objects.filter(profile_id=profile_id)
        .order_by("-computed_at", "-id")
        .first()
    )
    if row is None:
        return None
    return BaselineOut(
        profile_id=profile_id,
        window_days=row.window_days,
        n_posts=row.n_posts,
        median_views=row.median_views,
        median_engagement=row.median_engagement,
        p75_views=row.p75_views,
        reliable=row.baseline_reliable,
        computed_at=row.computed_at,
    )


def save_baseline(baseline: BaselineOut) -> None:
    """Insert-only: the newest row by ``computed_at`` is the current one."""
    ProfileBaseline.objects.create(
        profile_id=baseline.profile_id,
        window_days=baseline.window_days,
        n_posts=baseline.n_posts,
        median_views=baseline.median_views,
        median_engagement=baseline.median_engagement,
        p75_views=baseline.p75_views,
        baseline_reliable=baseline.reliable,
        computed_at=baseline.computed_at,
    )


# --------------------------------------------------------------------------- listening, alerts


def record_listening_match(
    profile_id: int, post_id: int, score: float | None = None
) -> bool:
    """``True`` when the match is new."""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO listening_matches (profile_id, post_id, discovered_at, score)"
            " VALUES (%s, %s, now(), %s) ON CONFLICT (profile_id, post_id) DO NOTHING RETURNING id",
            [profile_id, post_id, score],
        )
        return cursor.fetchone() is not None


def create_alert_once(
    profile_id: int,
    post_id: int,
    kind: str,
    *,
    trigger: str | None = None,
    velocity: float | None = None,
    baseline_velocity: float | None = None,
) -> bool:
    """Insert an active alert unless one is already active for (profile, post, kind).

    One atomic statement; safe between processes. ``True`` only if it inserted.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO alerts (profile_id, post_id, kind, trigger, status, velocity,"
            " baseline_velocity, created_at) VALUES (%s, %s, %s, %s, 'active', %s, %s, now())"
            " ON CONFLICT (profile_id, post_id, kind) WHERE status = 'active' DO NOTHING"
            " RETURNING id",
            [profile_id, post_id, kind, trigger, velocity, baseline_velocity],
        )
        return cursor.fetchone() is not None


def unread_alerts(profile_id: int) -> list[AlertOut]:
    rows = Alert.objects.filter(
        profile_id=profile_id, status=AlertStatus.ACTIVE
    ).order_by("-created_at", "-id")
    return [
        AlertOut(
            id=a.pk,
            profile_id=profile_id,
            post_id=a.post_id,
            kind=a.kind,
            created_at=a.created_at,
        )
        for a in rows
    ]


def unread_alert_details(profile_id: int) -> list[AlertDetail]:
    """Body of ``GET /profiles/{id}/alerts/unread``: one query with the post joined."""
    rows = (
        Alert.objects.filter(profile_id=profile_id, status=AlertStatus.ACTIVE)
        .select_related("post")
        .order_by("-created_at", "-id")
    )
    return [
        AlertDetail(
            id=a.pk,
            post_id=a.post_id,
            caption=a.post.caption,
            platform_post_id=a.post.platform_post_id,
            alerted_at=a.created_at,
            kind=a.kind,
            velocity=a.velocity,
            baseline_velocity=a.baseline_velocity,
        )
        for a in rows
    ]


def dismiss_alert(profile_id: int, alert_id: int) -> bool:
    """``False`` when the alert does not exist for the profile. Dismissing twice is a no-op."""
    owned = Alert.objects.filter(pk=alert_id, profile_id=profile_id)
    if not owned.exists():
        return False
    owned.filter(status=AlertStatus.ACTIVE).update(
        status=AlertStatus.DISMISSED, dismissed_at=timezone.now()
    )
    return True


def _clean_keywords(keywords: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for raw in keywords:
        word = (raw or "").strip()
        if not word:
            continue
        if len(word) > KEYWORD_MAX:
            raise ValueError(f"keyword longer than {KEYWORD_MAX} characters")
        if word.lower() not in seen:
            seen.add(word.lower())
            clean.append(word)
    return clean


def get_listening(profile_id: int) -> ListeningConfig:
    keywords = tuple(
        ListeningKeyword.objects.filter(profile_id=profile_id)
        .order_by("id")
        .values_list("keyword", flat=True)
    )
    poll = PollConfig.objects.filter(profile_id=profile_id).first()
    return ListeningConfig(
        profile_id=profile_id,
        keywords=keywords,
        enabled=bool(poll and poll.is_active),
        interval_minutes=poll.interval_minutes if poll else None,
    )


def set_listening(config: ListeningConfig) -> ListeningConfig:
    """Replace the keyword set and the poll settings in one transaction."""
    interval = config.interval_minutes
    if interval is not None and not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        raise ValueError(
            f"interval_minutes must be between {MIN_INTERVAL} and {MAX_INTERVAL}"
        )
    wanted = _clean_keywords(config.keywords)
    with transaction.atomic():
        profile = SocialProfile.objects.select_for_update().get(pk=config.profile_id)
        existing = {
            k.keyword.lower(): k
            for k in ListeningKeyword.objects.filter(profile=profile)
        }
        keep = {w.lower() for w in wanted}
        stale = [k.pk for key, k in existing.items() if key not in keep]
        if stale:
            ListeningKeyword.objects.filter(pk__in=stale).delete()
        ListeningKeyword.objects.bulk_create(
            [
                ListeningKeyword(profile=profile, keyword=w)
                for w in wanted
                if w.lower() not in existing
            ]
        )
        poll, _ = PollConfig.objects.get_or_create(
            profile=profile, defaults={"interval_minutes": interval or DEFAULT_INTERVAL}
        )
        poll.is_active = config.enabled
        if interval is not None:
            poll.interval_minutes = interval
        poll.save(update_fields=["is_active", "interval_minutes", "updated_at"])
    return get_listening(config.profile_id)


def claim_due_polls(limit: int = 50) -> list[int]:
    """Claim profiles whose poll is due. One ``UPDATE ... RETURNING``; two workers never claim
    the same profile (``FOR UPDATE SKIP LOCKED``)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE poll_configs SET last_polled_at = now() WHERE id IN ("
            " SELECT id FROM poll_configs WHERE is_active AND (last_polled_at IS NULL OR"
            " last_polled_at <= now() - interval_minutes * interval '1 minute')"
            " ORDER BY last_polled_at NULLS FIRST, id LIMIT %s FOR UPDATE SKIP LOCKED)"
            " RETURNING profile_id",
            [limit],
        )
        return sorted(row[0] for row in cursor.fetchall())


# --------------------------------------------------------------------------- analytics


_EMPTY_ANALYTICS = {
    "total_impressions": 0,
    "total_likes": 0,
    "total_comments": 0,
    "total_shares": 0,
    "reach_change_pct": 0.0,
    "saves_change_pct": 0.0,
    "reach_series": [],
    "saves_series": [],
    "allocation": [],
    "top_posts": [],
    "is_live_data": False,
}


def _delta_series(values: list[int]) -> list[float]:
    if not values:
        return []
    base = values[0] or 1
    return [round(((v - base) / base) * 100, 2) for v in values]


def get_analytics(profile_id: int) -> dict[str, Any] | None:
    """Read-only analytics body of ``GET /profiles/{id}/analytics`` (``None`` if no profile).

    Deviation from the legacy code: totals add the **latest** snapshot of each post. The legacy
    summed every snapshot, so a post read ten times counted ten times.
    """
    profile = (
        SocialProfile.objects.select_related("handle").filter(pk=profile_id).first()
    )
    if profile is None:
        return None
    base = {
        "profile_id": profile_id,
        "handle": profile.handle.handle_normalized,
        "name": _display_name(profile.handle),
    }
    posts = list(
        Post.objects.filter(
            author_id=profile.handle_id, kind=PostKind.ORIGINAL, is_stub=False
        ).only("id", "caption")
    )
    if not posts:
        return {**base, **_EMPTY_ANALYTICS, "summary": _no_data_summary(base["handle"])}
    snapshots = list(
        MetricSnapshot.objects.filter(post__in=[p.pk for p in posts])
        .order_by("captured_at", "id")
        .only("post_id", "views", "likes", "comments", "shares", "captured_at")
    )
    latest: dict[int, MetricSnapshot] = {}
    for snap in snapshots:  # ordered, so the last one wins
        latest[snap.post_id] = snap
    total_views = sum(s.views or 0 for s in latest.values())
    if total_views <= 0:
        return {**base, **_EMPTY_ANALYTICS, "summary": _no_data_summary(base["handle"])}
    paired = [(p, latest[p.pk]) for p in posts if p.pk in latest]
    text_views = sum(s.views or 0 for p, s in paired if len(p.caption.split()) < 30)
    image_views = sum(
        s.views or 0 for p, s in paired if 30 <= len(p.caption.split()) < 80
    )
    other_views = max(0, total_views - text_views - image_views)
    txt_pct = round(text_views / total_views * 100, 1)
    img_pct = round(image_views / total_views * 100, 1)
    reach = _delta_series([s.views or 0 for s in snapshots])
    saves = _delta_series([s.likes or 0 for s in snapshots])
    reach_change = reach[-1] if reach else 0.0
    return {
        **base,
        "total_impressions": total_views,
        "total_likes": sum(s.likes or 0 for s in latest.values()),
        "total_comments": sum(s.comments or 0 for s in latest.values()),
        "total_shares": sum(s.shares or 0 for s in latest.values()),
        "reach_change_pct": reach_change,
        "saves_change_pct": saves[-1] if saves else 0.0,
        "reach_series": reach,
        "saves_series": saves,
        "allocation": [
            {
                "name": "TXT",
                "label": "Text Posts",
                "pct": txt_pct,
                "amount": f"{text_views:,} views",
                "color": "#1d9bf0",
                "textColor": "var(--blue)",
            },
            {
                "name": "IMG",
                "label": "Image Cards",
                "pct": img_pct,
                "amount": f"{image_views:,} views",
                "color": "#f68f3c",
                "textColor": "var(--orange)",
            },
            {
                "name": "VID",
                "label": "Video / Rich",
                "pct": round(100.0 - txt_pct - img_pct, 1),
                "amount": f"{other_views:,} views",
                "color": "rgba(255,255,255,0.28)",
                "textColor": "var(--text-dim)",
            },
        ],
        "top_posts": [
            {
                "caption": p.caption[:120],
                "impressions": s.views or 0,
                "likes": s.likes or 0,
            }
            for p, s in sorted(paired, key=lambda x: x[1].views or 0, reverse=True)[:3]
        ],
        "is_live_data": True,
        "summary": (
            f"Your account @{base['handle']} generated {total_views:,} total impressions "
            f"({'+' if reach_change > 0 else ''}{reach_change}%). "
            f"Text posts account for {txt_pct}% of total views."
        ),
    }


def _no_data_summary(handle: str) -> str:
    return (
        f"No post analytics found for @{handle} yet. "
        "Data appears here after your posts are backfilled from Post for Me or Xpoz."
    )


# --------------------------------------------------------------------------- async twins

_ASYNC = (
    "get_profile",
    "list_profiles",
    "list_profile_summaries",
    "get_profile_summary",
    "select_info",
    "get_or_create_handle",
    "get_or_create_profile",
    "record_handle_snapshot",
    "list_posts",
    "get_posts",
    "list_activity",
    "upsert_posts",
    "append_metric_snapshots",
    "latest_baseline",
    "save_baseline",
    "mark_bootstrapped",
    "record_listening_match",
    "create_alert_once",
    "unread_alerts",
    "unread_alert_details",
    "dismiss_alert",
    "get_listening",
    "set_listening",
    "claim_due_polls",
    "get_analytics",
)
for _name in _ASYNC:
    globals()[f"a{_name}"] = sync_to_async(globals()[_name], thread_sensitive=True)
__all__ += list(_ASYNC) + [f"a{n}" for n in _ASYNC]
