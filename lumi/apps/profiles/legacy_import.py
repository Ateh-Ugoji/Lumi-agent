"""T8 importers for the tables ``profiles`` owns (SCHEMA.md section 10.1 and 10.2)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.db import connection

from apps.core.choices import IngestSource, Platform, PostKind
from apps.core.legacy_import import (
    ImportContext,
    Importer,
    register,
    to_bool,
    to_dt,
    to_json,
)
from apps.core.legacy_import.engine import sync_sequence
from apps.profiles import services
from apps.profiles.models import (
    Alert,
    AlertKind,
    AlertStatus,
    HandleSnapshot,
    KindSource,
    ListeningMatch,
    MetricSnapshot,
    PollConfig,
    Post,
    ProfileBaseline,
    SocialProfile,
    TimezoneSource,
)

BATCH = 2000
METRIC_COLUMNS = ("likes", "comments", "shares", "views")


def profile_targets(ctx: ImportContext) -> dict[int, tuple[int, int]]:
    """Legacy ``profiles.id`` to ``(social_profiles.id, social_handles.id)``.

    A profile merged into another one points at the survivor. Skipped profiles are absent.
    """
    mapped = ctx.mapped("profiles", "social_profiles")
    handles = dict(
        SocialProfile.objects.filter(pk__in=set(mapped.values())).values_list(
            "pk", "handle_id"
        )
    )
    return {int(k): (v, handles[v]) for k, v in mapped.items() if v in handles}


def _source(value: Any) -> str | None:
    text = str(value).lower() if value else None
    return text if text in IngestSource.values else None


def _nonneg(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _chunks(items: list, size: int = BATCH) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _alert(
    profile_id: int,
    post_id: int,
    kind: str,
    alerted_at: datetime,
    dismissed: bool,
) -> Alert:
    return Alert(
        profile_id=profile_id,
        post_id=post_id,
        kind=kind,
        trigger=None,
        status=AlertStatus.DISMISSED if dismissed else AlertStatus.ACTIVE,
        created_at=alerted_at,
    )


# --------------------------------------------------------------------------- profiles


def import_profiles(ctx: ImportContext) -> None:
    t = ctx.table("profiles")
    done = ctx.mapped("profiles", "social_profiles")
    by_key: dict[tuple[str, str], int] = {}  # handle key -> social_profiles.id
    claimed: dict[tuple[str, str], int] = {}  # handle key -> legacy id still to create
    deferred: list[tuple[dict[str, Any], tuple[str, str]]] = []
    new_rows: list[dict[str, Any]] = []
    rows = list(ctx.legacy.rows("profiles"))
    t.read = len(rows)

    # Rows imported before keep their handle key, so a new duplicate merges into them.
    for row in rows:
        platform = str(row.get("platform") or "x").lower()
        try:
            key = (
                platform,
                services.normalize_handle(platform, row.get("handle") or ""),
            )
        except services.InvalidHandle:
            continue
        if str(row["id"]) in done:
            by_key.setdefault(key, done[str(row["id"])])

    for row in rows:
        pk = row["id"]
        if ctx.is_done("profiles", pk, "social_profiles"):
            t.already += 1
            continue
        platform = str(row.get("platform") or "x").lower()
        if platform not in Platform.values:
            ctx.skip("profiles", row, f"plataforma desconocida {platform!r}")
            continue
        try:
            key = (
                platform,
                services.normalize_handle(platform, row.get("handle") or ""),
            )
        except services.InvalidHandle:
            ctx.skip("profiles", row, "handle no válido")
            continue
        if key in by_key:
            ctx.merge(
                "profiles",
                row,
                "social_profiles",
                by_key[key],
                f"mismo handle que el perfil {by_key[key]} "
                "(se fusiona y sus hijos pasan al otro)",
            )
            continue
        if key in claimed:
            deferred.append((row, key))
            continue
        claimed[key] = pk
        new_rows.append({**row, "_platform": platform, "_key": key})

    ctx.require_free_ids(SocialProfile, [r["id"] for r in new_rows])
    for row in new_rows:
        pk = row["id"]
        platform, key = row["_platform"], row["_key"]
        raw_handle = str(row.get("handle") or "").strip().lstrip("@")
        handle_id = services.get_or_create_handle(
            platform,
            raw_handle,
            origin="profile",
            display_name=str(row.get("name") or ""),
            handle_display=raw_handle,
        )
        existing = SocialProfile.objects.filter(
            user=ctx.user, handle_id=handle_id
        ).first()
        if existing:
            ctx.merge(
                "profiles",
                row,
                "social_profiles",
                existing.pk,
                f"el usuario ya tenía ese handle (perfil {existing.pk})",
            )
            by_key[key] = existing.pk
            continue
        tz = row.get("timezone") or None
        tz_source = row.get("timezone_source") or None
        adjusted = False
        if tz and tz_source not in TimezoneSource.values:
            adjusted = True
            tz_source = TimezoneSource.INFERRED
            ctx.warn(
                f"profiles {pk}: zona horaria sin origen válido, se marca 'inferred'"
            )
        if not tz:
            tz, tz_source = None, None
        extra = {}
        if created := to_dt(row.get("created_at")):
            extra["created_at"] = created
        SocialProfile.objects.create(
            id=pk,
            user=ctx.user,
            handle_id=handle_id,
            timezone=tz,
            timezone_source=tz_source,
            **extra,
        )
        ctx.remember(
            "profiles",
            pk,
            "social_profiles",
            pk,
            row=_original(row) if adjusted else None,
        )
        by_key[key] = pk
        t.imported += 1
    for row, key in deferred:
        ctx.merge(
            "profiles",
            row,
            "social_profiles",
            by_key[key],
            f"mismo handle que el perfil {by_key[key]} "
            "(se fusiona y sus hijos pasan al otro)",
        )
    sync_sequence(SocialProfile)


# ------------------------------------------------------------ snapshots and baselines


def _original(row: dict[str, Any]) -> dict[str, Any]:
    """The legacy row without the helper keys the importer adds while it works."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def import_snapshots_and_baselines(ctx: ImportContext) -> None:
    targets = profile_targets(ctx)
    _import_handle_snapshots(ctx, targets)
    _import_baselines(ctx, targets)


def _import_handle_snapshots(
    ctx: ImportContext, targets: dict[int, tuple[int, int]]
) -> None:
    t = ctx.table("profile_snapshots")
    rows = list(ctx.legacy.rows("profile_snapshots"))
    t.read = len(rows)
    pending: list[tuple[dict[str, Any], int, datetime]] = []
    for row in rows:
        if ctx.is_done("profile_snapshots", row["id"], "handle_snapshots"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        when = to_dt(row.get("captured_at"))
        if target is None or when is None:
            ctx.skip("profile_snapshots", row, "sin perfil importado o sin fecha")
            continue
        pending.append((row, target[1], when))

    handle_ids = {h for _, h, _ in pending}
    existing = {
        (h, ts): pk
        for h, ts, pk in HandleSnapshot.objects.filter(
            handle_id__in=handle_ids
        ).values_list("handle_id", "captured_at", "id")
    }
    winner: dict[tuple[int, datetime], dict[str, Any]] = {}
    for row, handle_id, when in pending:
        key = (handle_id, when)
        if key not in winner or row["id"] > winner[key]["id"]:
            winner[key] = row
    to_create = [
        HandleSnapshot(
            handle_id=h,
            captured_at=ts,
            followers=_nonneg(row.get("followers")),
            following=_nonneg(row.get("following")),
            source=_source(row.get("source")),
        )
        for (h, ts), row in winner.items()
        if (h, ts) not in existing
    ]
    for chunk in _chunks(to_create):
        HandleSnapshot.objects.bulk_create(chunk)
    for obj in to_create:
        existing[(obj.handle_id, obj.captured_at)] = obj.pk
    created_keys = {(o.handle_id, o.captured_at) for o in to_create}
    for row, handle_id, when in pending:
        key = (handle_id, when)
        if winner[key]["id"] == row["id"] and key in created_keys:
            ctx.remember(
                "profile_snapshots", row["id"], "handle_snapshots", existing[key]
            )
            t.imported += 1
        else:
            ctx.merge("profile_snapshots", row, "handle_snapshots", existing[key])
    if t.merged:
        ctx.warn(
            f"profile_snapshots: {t.merged} filas repetidas (handle, fecha) fusionadas"
        )


def _import_baselines(ctx: ImportContext, targets: dict[int, tuple[int, int]]) -> None:
    t = ctx.table("profile_baseline")
    rows = list(ctx.legacy.rows("profile_baseline"))
    t.read = len(rows)
    objs: list[tuple[int, ProfileBaseline]] = []
    for row in rows:
        if ctx.is_done("profile_baseline", row["id"], "profile_baselines"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip("profile_baseline", row, "sin perfil importado")
            continue
        kwargs: dict[str, Any] = {
            "profile_id": target[0],
            "window_days": max(int(row.get("window_days") or 90), 1),
            "n_posts": max(int(row.get("n_posts") or 0), 0),
            "median_views": max(float(row.get("median_views") or 0), 0.0),
            "median_engagement": max(float(row.get("median_engagement") or 0), 0.0),
            "p75_views": max(float(row.get("p75_views") or 0), 0.0),
            "baseline_reliable": to_bool(row.get("baseline_reliable")),
        }
        if computed := to_dt(row.get("computed_at")):
            kwargs["computed_at"] = computed
        objs.append((row["id"], ProfileBaseline(**kwargs)))
    for chunk in _chunks(objs):
        ProfileBaseline.objects.bulk_create([o for _, o in chunk])
    for legacy_id, obj in objs:
        ctx.remember("profile_baseline", legacy_id, "profile_baselines", obj.pk)
        t.imported += 1


# ----------------------------------------------------------------------------- posts


def import_posts(ctx: ImportContext) -> None:
    t = ctx.table("posts")
    targets = profile_targets(ctx)
    rows = list(ctx.legacy.rows("posts"))
    t.read = len(rows)
    pending: list[tuple[dict[str, Any], int, int]] = []
    for row in rows:
        if ctx.is_done("posts", row["id"], "posts"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None or not row.get("platform_post_id"):
            ctx.skip("posts", row, "sin perfil importado o sin id de plataforma")
            continue
        pending.append((row, *target))

    existing = _existing_posts(h for _, _, h in pending)
    new_posts: list[Post] = []
    alerts: list[Alert] = []
    adjusted_posts: set[int] = set()
    by_id = {r["id"]: r for r, _, _ in pending}
    for row, profile_id, handle_id in pending:
        key = (handle_id, str(row["platform_post_id"]))
        if key in existing:
            ctx.merge("posts", row, "posts", existing[key])
            _post_alert(alerts, row, profile_id, existing[key], AlertKind.SPIKE)
            continue
        existing[key] = row["id"]
        kind = str(row.get("kind") or "original").lower()
        if kind not in PostKind.values:
            adjusted_posts.add(row["id"])
            ctx.warn(
                f"posts {row['id']}: tipo {kind!r} desconocido, se guarda como original"
            )
            kind = PostKind.ORIGINAL
        kind_source = str(row.get("kind_source") or "").lower()
        thread_position = row.get("thread_position")
        new_posts.append(
            Post(
                id=row["id"],
                author_id=handle_id,
                platform_post_id=str(row["platform_post_id"]),
                kind=kind,
                kind_source=kind_source if kind_source in KindSource.values else None,
                caption=row.get("caption") or "",
                published_at=to_dt(row.get("published_at")),
                source=_source(row.get("source")),
                conversation_id=row.get("conversation_id") or "",
                thread_position=thread_position
                if isinstance(thread_position, int) and thread_position >= 1
                else None,
                is_thread_head=None
                if row.get("is_thread_head") is None
                else to_bool(row["is_thread_head"]),
                text_truncated=to_bool(row.get("text_truncated")),
                is_deleted_suspect=to_bool(row.get("is_deleted_suspect")),
                last_seen_at=to_dt(row.get("last_seen_at")),
            )
        )
        _post_alert(alerts, row, profile_id, row["id"], AlertKind.SPIKE)
    ctx.require_free_ids(Post, [p.id for p in new_posts])
    for chunk in _chunks(new_posts):
        Post.objects.bulk_create(chunk)
    for post in new_posts:
        ctx.remember(
            "posts",
            post.id,
            "posts",
            post.id,
            row=_original(by_id[post.id]) if post.id in adjusted_posts else None,
        )
        t.imported += 1
    sync_sequence(Post)
    _save_alerts(ctx, "posts", alerts)


def _existing_posts(handle_ids: Iterable[int]) -> dict[tuple[int, str], int]:
    return {
        (a, p): pk
        for a, p, pk in Post.objects.filter(author_id__in=set(handle_ids)).values_list(
            "author_id", "platform_post_id", "id"
        )
    }


def _post_alert(
    alerts: list[Alert], row: dict[str, Any], profile_id: int, post_id: int, kind: str
) -> None:
    if when := to_dt(row.get("alerted_at")):
        alerts.append(
            _alert(profile_id, post_id, kind, when, to_bool(row.get("alert_dismissed")))
        )


def _save_alerts(ctx: ImportContext, source_table: str, alerts: list[Alert]) -> None:
    for chunk in _chunks(alerts):
        Alert.objects.bulk_create(chunk, ignore_conflicts=True)
    if alerts:
        ctx.table(source_table)  # keep the table in the report even when empty
        ctx.warn(f"{source_table}: {len(alerts)} alertas creadas desde alerted_at")


# ----------------------------------------------------------------------------- metrics


def import_metrics(ctx: ImportContext) -> None:
    t = ctx.table("metric_snapshots")
    posts = ctx.mapped("posts", "posts")
    rows = list(ctx.legacy.rows("metric_snapshots"))
    t.read = len(rows)
    pending: list[tuple[dict[str, Any], int, datetime]] = []
    for row in rows:
        if ctx.is_done("metric_snapshots", row["id"], "metric_snapshots"):
            t.already += 1
            continue
        post_id = posts.get(str(row["post_id"]))
        when = to_dt(row.get("captured_at"))
        if post_id is None or when is None:
            ctx.skip("metric_snapshots", row, "sin post importado o sin fecha")
            continue
        pending.append((row, post_id, when))

    existing: dict[tuple[int, datetime], int] = {}
    post_ids = sorted({p for _, p, _ in pending})
    for chunk in _chunks(post_ids, 5000):
        existing.update(
            {
                (p, ts): pk
                for p, ts, pk in MetricSnapshot.objects.filter(
                    post_id__in=chunk
                ).values_list("post_id", "captured_at", "id")
            }
        )
    winner: dict[tuple[int, datetime], dict[str, Any]] = {}
    for row, post_id, when in pending:
        key = (post_id, when)
        if key not in winner or row["id"] > winner[key]["id"]:
            winner[key] = row
    negatives = 0
    adjusted_metrics: set[int] = set()
    to_create: list[MetricSnapshot] = []
    for (post_id, when), row in winner.items():
        if (post_id, when) in existing:
            continue
        values = {}
        for column in METRIC_COLUMNS:
            raw = row.get(column)
            values[column] = _nonneg(raw)
            if raw is not None and values[column] is None:
                negatives += 1
                adjusted_metrics.add(row["id"])
        to_create.append(
            MetricSnapshot(
                post_id=post_id,
                captured_at=when,
                source=_source(row.get("source")),
                **values,
            )
        )
    for chunk in _chunks(to_create):
        MetricSnapshot.objects.bulk_create(chunk)
    created_keys = set()
    for obj in to_create:
        existing[(obj.post_id, obj.captured_at)] = obj.pk
        created_keys.add((obj.post_id, obj.captured_at))
    for row, post_id, when in pending:
        key = (post_id, when)
        if winner[key]["id"] == row["id"] and key in created_keys:
            ctx.remember(
                "metric_snapshots",
                row["id"],
                "metric_snapshots",
                existing[key],
                row=_original(row) if row["id"] in adjusted_metrics else None,
            )
            t.imported += 1
        else:
            ctx.merge("metric_snapshots", row, "metric_snapshots", existing[key])
    if t.merged:
        ctx.warn(
            f"metric_snapshots: {t.merged} lecturas repetidas (post, fecha) fusionadas"
        )
    if negatives:
        ctx.warn(f"metric_snapshots: {negatives} métricas negativas pasaron a NULL")


def stamp_last_checked(ctx: ImportContext) -> None:
    """Fill ``posts.last_checked_at`` from the newest metric snapshot of each post.

    The legacy code has no "last checked" column. It appended a snapshot every 6 hours even when
    nothing changed, so its newest snapshot is the best record of the last check. Posts without
    snapshots stay NULL (nobody checked them). Never lowers a stamp: idempotent.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE posts SET last_checked_at = s.newest FROM ("
            " SELECT post_id, max(captured_at) AS newest FROM metric_snapshots GROUP BY post_id"
            ") s WHERE posts.id = s.post_id"
            " AND (posts.last_checked_at IS NULL OR posts.last_checked_at < s.newest)"
        )
        if cursor.rowcount:
            ctx.warn(
                f"posts: last_checked_at tomado de la última lectura en {cursor.rowcount} posts"
            )


# ------------------------------------------------------------------------- user activity


def import_activity(ctx: ImportContext) -> None:
    t = ctx.table("user_activity")
    targets = profile_targets(ctx)
    rows = list(ctx.legacy.rows("user_activity"))
    t.read = len(rows)
    pending: list[tuple[dict[str, Any], int, int]] = []
    for row in rows:
        if ctx.is_done("user_activity", row["id"], "posts"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        kind = str(row.get("kind") or "").lower()
        if target is None or not row.get("platform_post_id"):
            ctx.skip(
                "user_activity", row, "sin perfil importado o sin id de plataforma"
            )
        elif kind not in {PostKind.REPLY, PostKind.RETWEET, PostKind.QUOTE}:
            ctx.skip("user_activity", row, f"tipo {kind!r} no admitido")
        else:
            pending.append((row, *target))

    existing = _existing_posts(h for _, _, h in pending)
    for row, _profile_id, handle_id in pending:
        key = (handle_id, str(row["platform_post_id"]))
        if key in existing:
            ctx.merge(
                "user_activity",
                row,
                "posts",
                existing[key],
                "el post ya existe, gana la fila de posts",
            )
            continue
        post = Post.objects.create(
            author_id=handle_id,
            platform_post_id=str(row["platform_post_id"]),
            kind=str(row["kind"]).lower(),
            caption=row.get("caption") or "",
            published_at=to_dt(row.get("published_at")),
            source=_source(row.get("source")),
        )
        existing[key] = post.pk
        likes, replies, views = (
            _nonneg(row.get(c)) for c in ("likes", "replies", "views")
        )
        when = to_dt(row.get("created_at"))
        if when and any(v is not None for v in (likes, replies, views)):
            MetricSnapshot.objects.create(
                post=post,
                captured_at=when,
                source=_source(row.get("source")),
                likes=likes,
                comments=replies,
                views=views,
            )
        ctx.remember("user_activity", row["id"], "posts", post.pk)
        t.imported += 1


# -------------------------------------------------------------------- listening matches


def _metrics_from_json(raw: Any) -> dict[str, int | None]:
    data = to_json(raw)
    if not isinstance(data, dict):
        return {}

    def pick(*names: str) -> int | None:
        for name in names:
            if _nonneg(data.get(name)) is not None:
                return data[name]
        return None

    return {
        "likes": pick("likes"),
        "comments": pick("replies", "comments"),
        "shares": pick("retweets", "shares"),
        "views": pick("views", "impressions"),
    }


def import_listening(ctx: ImportContext) -> None:
    t = ctx.table("listening_matches")
    targets = profile_targets(ctx)
    rows = list(ctx.legacy.rows("listening_matches"))
    t.read = len(rows)
    handles: dict[tuple[str, str], int] = {}
    alerts: list[Alert] = []
    for row in rows:
        pk = row["id"]
        if ctx.is_done("listening_matches", pk, "listening_matches"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        platform = str(row.get("platform") or "x").lower()
        if target is None or not row.get("platform_post_id"):
            ctx.skip(
                "listening_matches", row, "sin perfil importado o sin id de plataforma"
            )
            continue
        try:
            normalized = services.normalize_handle(
                platform, row.get("author_handle") or ""
            )
        except services.InvalidHandle:
            ctx.skip("listening_matches", row, "autor con handle no válido")
            continue
        profile_id = target[0]
        handle_id = handles.get((platform, normalized))
        if handle_id is None:
            handle_id = handles[(platform, normalized)] = services.get_or_create_handle(
                platform,
                normalized,
                origin="niche",
                handle_display=str(row["author_handle"]).strip().lstrip("@"),
            )
        platform_post_id = str(row["platform_post_id"])
        post = Post.objects.filter(
            author_id=handle_id, platform_post_id=platform_post_id
        ).first()
        discovered = to_dt(row.get("discovered_at"))
        post_is_new = post is None
        if post is None:
            post = Post.objects.create(
                author_id=handle_id,
                platform_post_id=platform_post_id,
                kind=PostKind.ORIGINAL,
                caption=row.get("caption") or "",
                url=row.get("platform_url") or "",
            )
            metrics = _metrics_from_json(row.get("metrics"))
            if discovered and any(v is not None for v in metrics.values()):
                MetricSnapshot.objects.create(
                    post=post, captured_at=discovered, **metrics
                )
        match = ListeningMatch.objects.filter(profile_id=profile_id, post=post).first()
        if match:
            ctx.merge(
                "listening_matches",
                row,
                "listening_matches",
                match.pk,
                "ya había una coincidencia para ese post",
            )
        else:
            extra = {"discovered_at": discovered} if discovered else {}
            match = ListeningMatch.objects.create(
                profile_id=profile_id, post=post, **extra
            )
            # An existing post keeps its own caption, url and metrics, so this row's copy
            # of them stays in the payload.
            ctx.remember(
                "listening_matches",
                pk,
                "listening_matches",
                match.pk,
                row=None if post_is_new else _original(row),
            )
            t.imported += 1
        _post_alert(alerts, row, profile_id, post.pk, AlertKind.NICHE_MATCH)
    _save_alerts(ctx, "listening_matches", alerts)


# --------------------------------------------------------------------------- poll config


def import_poll_config(ctx: ImportContext) -> None:
    t = ctx.table("poll_config")
    targets = profile_targets(ctx)
    rows = list(ctx.legacy.rows("poll_config"))
    t.read = len(rows)
    for row in rows:
        pk = row["id"]
        if ctx.is_done("poll_config", pk, "poll_configs"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip("poll_config", row, "sin perfil importado")
            continue
        existing = PollConfig.objects.filter(profile_id=target[0]).first()
        if existing:
            ctx.merge(
                "poll_config",
                row,
                "poll_configs",
                existing.pk,
                f"el perfil {target[0]} ya tiene configuración",
            )
            continue
        interval = int(row.get("interval_minutes") or 5)
        adjusted = not 1 <= interval <= 1440
        if adjusted:
            ctx.warn(
                f"poll_config {pk}: intervalo {interval} fuera de 1 a 1440, se ajusta"
            )
            interval = min(max(interval, 1), 1440)
        config = PollConfig.objects.create(
            profile_id=target[0],
            interval_minutes=interval,
            is_active=to_bool(row.get("is_active")),
            last_polled_at=to_dt(row.get("last_polled_at")),
        )
        ctx.remember(
            "poll_config",
            pk,
            "poll_configs",
            config.pk,
            row=_original(row) if adjusted else None,
        )
        t.imported += 1


for _importer in (
    Importer("profiles", ("profiles",), 10, import_profiles),
    Importer(
        "profile_history",
        ("profile_snapshots", "profile_baseline"),
        20,
        import_snapshots_and_baselines,
    ),
    Importer("posts", ("posts",), 30, import_posts),
    Importer("metrics", ("metric_snapshots",), 40, import_metrics),
    Importer("activity", ("user_activity",), 50, import_activity),
    Importer("listening", ("listening_matches",), 60, import_listening),
    Importer("last_checked", (), 65, stamp_last_checked),
    Importer("poll_config", ("poll_config",), 70, import_poll_config),
):
    register(_importer)

__all__ = ["profile_targets"]
