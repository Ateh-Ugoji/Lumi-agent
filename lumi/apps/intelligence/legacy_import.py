"""T8 importers of the INTELLIGENCE tables (SCHEMA.md section 10.4, orders 100-199).

Rule of the whole import: no legacy row is lost. A row ends up imported, merged into another
row or skipped, and a row that the new tables hold only in part (an adjusted value, a dropped
orphan id, a merged duplicate) keeps its full content in ``legacy_import_map.payload``.
New ids are assigned by the database: the maps, not the ids, are the link to the legacy rows.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from django.db.models import F

from apps.core.choices import Platform
from apps.core.legacy_import import (
    ImportContext,
    Importer,
    register,
    to_bool,
    to_dt,
    to_json,
)
from apps.intelligence.models import (
    GENERAL,
    JudgeVerdict,
    NicheReport,
    PathTaken,
    PostTagging,
    ProfileMemorySummary,
    ReportOrigin,
    ReportStatus,
    RepurposeAttempt,
    RepurposeRequest,
    RouteLabel,
    StyleAnswer,
    TaggingStatus,
    TurnClassification,
    UserAction,
    UserActionKind,
    UserSearchRequest,
    VoiceProfile,
    VoiceProfileExample,
    VoiceSource,
)
from apps.profiles import services
from apps.profiles.legacy_import import profile_targets
from apps.profiles.models import Post, SocialHandle

BATCH = 2000


def _chunks(items: list, size: int = BATCH) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _create(model, objs: list) -> None:
    for chunk in _chunks(objs):
        model.objects.bulk_create(chunk)


def _created(row: dict[str, Any]) -> dict[str, Any]:
    stamp = to_dt(row.get("created_at"))
    return {"created_at": stamp} if stamp else {}


def _platforms(targets: dict[int, tuple[int, int]]) -> dict[int, str]:
    """``social_handles.id`` to its platform, for the handles of the imported profiles."""
    ids = {handle_id for _, handle_id in targets.values()}
    return dict(SocialHandle.objects.filter(pk__in=ids).values_list("pk", "platform"))


def _text(value: Any, limit: int | None = None) -> tuple[str, bool]:
    """``(text, was_cut)``: ``None`` becomes ``''`` and a long text is cut to ``limit``."""
    text = "" if value is None else str(value)
    if limit is not None and len(text) > limit:
        return text[:limit], True
    return text, False


# -- 100: search requests and style answers ----------------------------------


def import_search_and_style(ctx: ImportContext) -> None:
    targets = profile_targets(ctx)
    platforms = _platforms(targets)
    _search_requests(ctx, targets, platforms)
    _style_answers(ctx, targets)


def _search_requests(ctx, targets, platforms) -> None:
    t = ctx.table("user_search_requests")
    rows = list(ctx.legacy.rows("user_search_requests"))
    t.read = len(rows)
    made: list[tuple[dict, UserSearchRequest]] = []
    for row in rows:
        if ctx.is_done("user_search_requests", row["id"], "user_search_requests"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip("user_search_requests", row, "sin perfil importado")
            continue
        platform = platforms.get(target[1], Platform.X)
        try:
            handle_id = services.get_or_create_handle(
                platform, row["handle"], origin="import"
            )
        except services.InvalidHandle:
            ctx.skip("user_search_requests", row, "handle no válido")
            continue
        note, _ = _text(row.get("request_note"))
        made.append(
            (
                row,
                UserSearchRequest(
                    profile_id=target[0],
                    handle_id=handle_id,
                    request_note=note,
                    **_created(row),
                ),
            )
        )
    _create(UserSearchRequest, [o for _, o in made])
    for row, obj in made:
        ctx.remember("user_search_requests", row["id"], "user_search_requests", obj.pk)
        t.imported += 1


def _style_answers(ctx, targets) -> None:
    t = ctx.table("style_answers")
    rows = list(ctx.legacy.rows("style_answers"))
    t.read = len(rows)
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        if ctx.is_done("style_answers", row["id"], "style_answers"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip("style_answers", row, "sin perfil importado")
            continue
        groups[(target[0], str(row["question_key"])[:80])].append(row)
    existing = {
        (p, k): pk
        for pk, p, k in StyleAnswer.objects.filter(
            profile_id__in={g[0] for g in groups}
        ).values_list("pk", "profile_id", "question_key")
    }
    made: list[tuple[tuple[int, str], dict, StyleAnswer]] = []
    for key, group in groups.items():
        if key in existing:
            for row in group:
                ctx.merge(
                    "style_answers",
                    row,
                    "style_answers",
                    existing[key],
                    "la respuesta ya existía en la base nueva",
                )
            continue
        winner = group[-1]  # rows come ordered by id: the highest id wins
        made.append(
            (
                key,
                winner,
                StyleAnswer(
                    profile_id=key[0],
                    question_key=key[1],
                    answer=winner["answer"] or "",
                    **_created(winner),
                ),
            )
        )
    _create(StyleAnswer, [o for _, _, o in made])
    for key, winner, obj in made:
        ctx.remember("style_answers", winner["id"], "style_answers", obj.pk)
        t.imported += 1
        for old in groups[key][:-1]:
            ctx.merge(
                "style_answers",
                old,
                "style_answers",
                obj.pk,
                f"respuesta antigua de '{key[1]}' sustituida por la id {winner['id']}",
            )
    # SCHEMA 10.4: ``updated_at = created_at`` (``auto_now`` stamped the import time).
    for chunk in _chunks([o.pk for _, _, o in made]):
        StyleAnswer.objects.filter(pk__in=chunk).update(updated_at=F("created_at"))


# -- 110: voice profiles ------------------------------------------------------


def import_voice(ctx: ImportContext) -> None:
    t = ctx.table("voice_profiles")
    targets = profile_targets(ctx)
    platforms = _platforms(targets)
    posts = ctx.mapped("posts", "posts")
    rows = list(ctx.legacy.rows("voice_profiles"))
    t.read = len(rows)
    pending: dict[tuple[int, str, int], dict] = {}
    followers: dict[tuple[int, str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if ctx.is_done("voice_profiles", row["id"], "voice_profiles"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        version = row.get("version")
        if target is None or not isinstance(version, int) or version < 1:
            ctx.skip("voice_profiles", row, "sin perfil importado o versión no válida")
            continue
        platform = platforms.get(target[1])
        platform = platform if platform else GENERAL
        key = (target[0], platform, version)
        if key in pending:
            followers[key].append(row)
        else:
            pending[key] = row
    sps = {k[0] for k in pending}
    taken = {
        (p, pl, v): pk
        for pk, p, pl, v in VoiceProfile.objects.filter(profile_id__in=sps).values_list(
            "pk", "profile_id", "platform", "version"
        )
    }
    has_current = set(
        VoiceProfile.objects.filter(profile_id__in=sps, is_current=True).values_list(
            "profile_id", "platform"
        )
    )
    keep = {k: r for k, r in pending.items() if k not in taken}
    for key, row in pending.items():
        if key in taken:
            for each in [row, *followers[key]]:
                ctx.merge(
                    "voice_profiles",
                    each,
                    "voice_profiles",
                    taken[key],
                    "esa versión de voz ya existía en la base nueva",
                )
    # One current voice per (profile, platform): the highest version flagged current.
    newest: dict[tuple[int, str], int] = {}
    for (sp, platform, version), row in keep.items():
        if to_bool(row.get("is_current")) and version > newest.get((sp, platform), 0):
            newest[(sp, platform)] = version
    made: list[tuple[tuple, dict, VoiceProfile, list[tuple[int, int]], bool]] = []
    for key, row in keep.items():
        sp, platform, version = key
        legacy_current = to_bool(row.get("is_current"))
        current = (
            legacy_current
            and newest.get((sp, platform)) == version
            and (sp, platform) not in has_current
        )
        payload = to_json(row.get("payload"))
        adjusted = legacy_current != current or not isinstance(payload, dict)
        examples, example_adjusted = _voice_examples(row, posts)
        made.append(
            (
                key,
                row,
                VoiceProfile(
                    profile_id=sp,
                    platform=platform,
                    version=version,
                    is_current=current,
                    source=VoiceSource.POSTS,
                    payload=payload if isinstance(payload, dict) else {},
                    **_created(row),
                ),
                examples,
                adjusted or example_adjusted,
            )
        )
    _create(VoiceProfile, [vp for _, _, vp, _, _ in made])
    links: list[VoiceProfileExample] = []
    for key, row, vp, examples, adjusted in made:
        ctx.remember(
            "voice_profiles",
            row["id"],
            "voice_profiles",
            vp.pk,
            row=row if adjusted else None,
        )
        t.imported += 1
        links += [
            VoiceProfileExample(voice_profile_id=vp.pk, post_id=post, position=pos)
            for pos, post in examples
        ]
        for old in followers[key]:
            ctx.merge(
                "voice_profiles",
                old,
                "voice_profiles",
                vp.pk,
                "versión repetida al unir perfiles",
            )
    _create(VoiceProfileExample, links)


def _voice_examples(
    row: dict, posts: dict[str, int]
) -> tuple[list[tuple[int, int]], bool]:
    """``[(position, new post id)]`` and whether an id had to be dropped."""
    ids = to_json(row.get("example_post_ids"))
    if not isinstance(ids, list):
        return [], ids is not None
    kept: list[tuple[int, int]] = []
    seen: set[int] = set()
    dropped = False
    for position, legacy_id in enumerate(ids):
        post = posts.get(str(legacy_id))
        if post is None or post in seen or position > 32767:
            dropped = True
            continue
        seen.add(post)
        kept.append((position, post))
    return kept, dropped


# -- 120: post taggings -------------------------------------------------------


def _tagging_status(raw: Any) -> tuple[str, bool]:
    status = str(raw or "").lower()
    return (
        (status, False)
        if status in TaggingStatus.values
        else (TaggingStatus.FAILED, True)
    )


def _existing_taggings(post_ids: set[int]) -> dict[tuple[int, str], int]:
    out: dict[tuple[int, str], int] = {}
    for chunk in _chunks(sorted(post_ids), 5000):
        out.update(
            {
                (p, v): pk
                for pk, p, v in PostTagging.objects.filter(
                    post_id__in=chunk
                ).values_list("pk", "post_id", "prompt_version")
            }
        )
    return out


def import_taggings(ctx: ImportContext) -> None:
    _own_post_analysis(ctx)
    _post_taggings(ctx)


def _own_post_analysis(ctx) -> None:
    t = ctx.table("own_post_analysis")
    posts = ctx.mapped("posts", "posts")
    rows = list(ctx.legacy.rows("own_post_analysis"))
    t.read = len(rows)
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        if ctx.is_done("own_post_analysis", row["id"], "post_taggings"):
            t.already += 1
            continue
        post = posts.get(str(row["post_id"]))
        if post is None:
            ctx.skip("own_post_analysis", row, "el post no se importó")
            continue
        version, _ = _text(row.get("prompt_version"), 40)
        groups[(post, version)].append(row)
    existing = _existing_taggings({k[0] for k in groups})
    made: list[tuple[tuple[int, str], dict, PostTagging, bool]] = []
    for key, group in groups.items():
        if key in existing:
            for row in group:
                ctx.merge(
                    "own_post_analysis",
                    row,
                    "post_taggings",
                    existing[key],
                    "ya había un etiquetado para ese post y versión",
                )
            continue
        winner = group[-1]
        status, adjusted = _tagging_status(winner.get("status"))
        analysis = to_json(winner.get("analysis"))
        made.append(
            (
                key,
                winner,
                PostTagging(
                    post_id=key[0],
                    prompt_version=key[1],
                    status=status,
                    analysis=analysis,
                    tagged_at=to_dt(winner.get("created_at"))
                    if status == TaggingStatus.OK
                    else None,
                    **_created(winner),
                ),
                adjusted,
            )
        )
    _create(PostTagging, [o for _, _, o, _ in made])
    for key, winner, obj, adjusted in made:
        ctx.remember(
            "own_post_analysis",
            winner["id"],
            "post_taggings",
            obj.pk,
            row=winner if adjusted else None,
        )
        t.imported += 1
        for old in groups[key][:-1]:
            ctx.merge(
                "own_post_analysis",
                old,
                "post_taggings",
                obj.pk,
                "análisis antiguo del mismo post y versión",
            )


def _post_taggings(ctx) -> None:
    t = ctx.table("post_taggings")
    rows = list(ctx.legacy.rows("post_taggings"))
    t.read = len(rows)
    todo: list[tuple[dict, str, str]] = []
    for row in rows:
        if ctx.is_done("post_taggings", row["id"], "post_taggings"):
            t.already += 1
            continue
        try:
            handle = services.normalize_handle(Platform.X, row.get("handle") or "")
        except services.InvalidHandle:
            ctx.skip("post_taggings", row, "handle no válido")
            continue
        todo.append((row, handle, str(row["post_id"])))
    found: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for chunk in _chunks(sorted({pid for _, _, pid in todo}), 5000):
        for pk, pid, handle, platform in Post.objects.filter(
            platform_post_id__in=chunk
        ).values_list(
            "pk", "platform_post_id", "author__handle_normalized", "author__platform"
        ):
            found[(handle, pid)].append((pk, platform))
    resolved: dict[tuple[str, str], int] = {}
    for _row, handle, pid in todo:
        key = (handle, pid)
        if key in resolved:
            continue
        candidates = found.get(key, [])
        on_x = [pk for pk, platform in candidates if platform == Platform.X]
        if len(on_x) == 1:
            resolved[key] = on_x[0]
        elif len(candidates) == 1:
            resolved[key] = candidates[0][0]
        elif not candidates:
            author = services.get_or_create_handle(Platform.X, handle, origin="import")
            resolved[key] = Post.objects.create(
                author_id=author, platform_post_id=pid[:64], is_stub=True
            ).pk
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row, handle, pid in todo:
        post = resolved.get((handle, pid))
        if post is None:
            ctx.skip("post_taggings", row, "el post existe en varias plataformas")
            continue
        version, _ = _text(row.get("prompt_version"), 40)
        groups[(post, version)].append(row)
    existing = _existing_taggings({k[0] for k in groups})
    made: list[tuple[tuple[int, str], dict, PostTagging, bool]] = []
    for key, group in groups.items():
        if key in existing:
            for row in group:
                ctx.merge(
                    "post_taggings",
                    row,
                    "post_taggings",
                    existing[key],
                    "ya había un etiquetado para ese post y versión",
                )
            continue
        winner = group[-1]
        status, adjusted = _tagging_status(winner.get("status"))
        guess, cut = _text(winner.get("framework_guess"), 120)
        tagged = to_dt(winner.get("tagged_at"))
        made.append(
            (
                key,
                winner,
                PostTagging(
                    post_id=key[0],
                    prompt_version=key[1],
                    status=status,
                    analysis=to_json(winner.get("analysis")),
                    framework_guess=guess,
                    validation_error=_text(winner.get("validation_error"))[0],
                    tagged_at=tagged,
                    **({"created_at": tagged} if tagged else {}),
                ),
                adjusted or cut,
            )
        )
    _create(PostTagging, [o for _, _, o, _ in made])
    for key, winner, obj, adjusted in made:
        ctx.remember(
            "post_taggings",
            winner["id"],
            "post_taggings",
            obj.pk,
            row=winner if adjusted else None,
        )
        t.imported += 1
        for old in groups[key][:-1]:
            ctx.merge(
                "post_taggings",
                old,
                "post_taggings",
                obj.pk,
                "etiquetado antiguo del mismo post y versión",
            )


# -- 130: niche reports -------------------------------------------------------


def import_reports(ctx: ImportContext) -> None:
    targets = profile_targets(ctx)
    imported = _reports(
        ctx, targets, "peer_frameworks", ReportOrigin.LEGACY_PEER_FRAMEWORKS
    )
    imported += _reports(
        ctx, targets, "niche_framework_reports", ReportOrigin.LEGACY_NICHE_REPORT
    )
    if imported:
        ctx.warn(
            "informes de nicho importados con su payload crudo en niche_reports.report; "
            "frameworks, evidencias y pares no se derivan de él"
        )


def _count(value: Any) -> tuple[int, bool]:
    return (
        (value, False)
        if isinstance(value, int) and value >= 0
        else (0, value is not None)
    )


def _reports(ctx, targets, source: str, origin: str) -> int:
    t = ctx.table(source)
    rows = list(ctx.legacy.rows(source))
    t.read = len(rows)
    made: list[tuple[dict, NicheReport, bool]] = []
    for row in rows:
        if ctx.is_done(source, row["id"], "niche_reports"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip(source, row, "sin perfil importado")
            continue
        payload = to_json(row.get("payload"))
        adjusted = False
        if source == "peer_frameworks":
            query, niche = row.get("query") or "", row.get("niche_title") or ""
            status = ReportStatus.OK if payload else ReportStatus.FAILED
            posts_n = winners = 0
            peers, bad = _count(row.get("analyzed_peers_count"))
            adjusted |= bad
        else:
            query, niche = "", row.get("niche") or ""
            raw = str(row.get("status") or "").lower()
            status = raw if raw in ReportStatus.values else ReportStatus.FAILED
            adjusted |= status != raw
            posts_n, bad = _count(row.get("posts_analyzed"))
            adjusted |= bad
            winners, bad = _count(row.get("winner_count"))
            adjusted |= bad
            peers = 0
        if not isinstance(payload, dict | list):
            payload, adjusted = {}, True
        niche, cut = _text(niche, 200)
        made.append(
            (
                row,
                NicheReport(
                    profile_id=target[0],
                    query=query,
                    niche=niche,
                    status=status,
                    posts_analyzed=posts_n,
                    winner_count=winners,
                    peers_analyzed=peers,
                    report=payload,
                    origin=origin,
                    **_created(row),
                ),
                adjusted or cut,
            )
        )
    _create(NicheReport, [o for _, o, _ in made])
    for row, obj, adjusted in made:
        ctx.remember(
            source, row["id"], "niche_reports", obj.pk, row=row if adjusted else None
        )
        t.imported += 1
    return len(made)


# -- 140: repurpose -----------------------------------------------------------


def import_repurpose(ctx: ImportContext) -> None:
    targets = profile_targets(ctx)
    _requests(ctx, targets)
    _attempts(ctx)
    _actions(ctx)


def _requests(ctx, targets) -> None:
    t = ctx.table("repurpose_requests")
    rows = list(ctx.legacy.rows("repurpose_requests"))
    t.read = len(rows)
    made: list[tuple[dict, RepurposeRequest, bool]] = []
    for row in rows:
        if ctx.is_done("repurpose_requests", row["id"], "repurpose_requests"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip("repurpose_requests", row, "sin perfil importado")
            continue
        label = str(row["route_label"]).lower() if row.get("route_label") else None
        unknown = label is not None and label not in RouteLabel.values
        made.append(
            (
                row,
                RepurposeRequest(
                    profile_id=target[0],
                    source_caption=row.get("source_caption") or "",
                    route_label=None if unknown else label,
                    **_created(row),
                ),
                unknown,
            )
        )
    _create(RepurposeRequest, [o for _, o, _ in made])
    for row, obj, adjusted in made:
        ctx.remember(
            "repurpose_requests",
            row["id"],
            "repurpose_requests",
            obj.pk,
            row=row if adjusted else None,
        )
        t.imported += 1


def _attempts(ctx) -> None:
    t = ctx.table("repurpose_attempts")
    requests = ctx.mapped("repurpose_requests", "repurpose_requests")
    rows = list(ctx.legacy.rows("repurpose_attempts"))
    t.read = len(rows)
    groups: dict[tuple[int, str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if ctx.is_done("repurpose_attempts", row["id"], "repurpose_attempts"):
            t.already += 1
            continue
        request = requests.get(str(row["request_id"]))
        platform = str(row.get("platform") or "").lower()
        number = row.get("attempt_no")
        if (
            request is None
            or platform not in Platform.values
            or not isinstance(number, int)
            or number < 1
        ):
            ctx.skip(
                "repurpose_attempts", row, "sin solicitud, plataforma o número válidos"
            )
            continue
        groups[(request, platform, number)].append(row)
    existing = {
        (r, p, n): pk
        for pk, r, p, n in RepurposeAttempt.objects.filter(
            request_id__in={k[0] for k in groups}
        ).values_list("pk", "request_id", "platform", "attempt_no")
    }
    made: list[tuple[tuple, dict, RepurposeAttempt, bool]] = []
    for key, group in groups.items():
        if key in existing:
            for row in group:
                ctx.merge(
                    "repurpose_attempts",
                    row,
                    "repurpose_attempts",
                    existing[key],
                    "ese intento ya existía en la base nueva",
                )
            continue
        row = group[0]  # the first attempt written is the one the user saw
        verdict = (
            str(row["judge_verdict"]).lower() if row.get("judge_verdict") else None
        )
        bad_verdict = verdict is not None and verdict not in JudgeVerdict.values
        confidence = row.get("judge_confidence")
        bad_conf = confidence is not None and not 0 <= confidence <= 1
        made.append(
            (
                key,
                row,
                RepurposeAttempt(
                    request_id=key[0],
                    platform=key[1],
                    tier=row.get("tier"),
                    model=row.get("model"),
                    provider=row.get("provider"),
                    attempt_no=key[2],
                    output=row.get("output") or "",
                    must_keep_passed=to_bool(row.get("must_keep_passed")),
                    judge_verdict=None if bad_verdict else verdict,
                    judge_confidence=None if bad_conf else confidence,
                    is_fallback=False,
                    **_created(row),
                ),
                bad_verdict or bad_conf,
            )
        )
    _create(RepurposeAttempt, [o for _, _, o, _ in made])
    for key, row, obj, adjusted in made:
        ctx.remember(
            "repurpose_attempts",
            row["id"],
            "repurpose_attempts",
            obj.pk,
            row=row if adjusted else None,
        )
        t.imported += 1
        for other in groups[key][1:]:
            ctx.merge(
                "repurpose_attempts",
                other,
                "repurpose_attempts",
                obj.pk,
                "intento repetido con el mismo número",
            )


def _actions(ctx) -> None:
    t = ctx.table("user_actions")
    attempts = ctx.mapped("repurpose_attempts", "repurpose_attempts")
    rows = list(ctx.legacy.rows("user_actions"))
    t.read = len(rows)
    made: list[tuple[dict, UserAction, bool]] = []
    for row in rows:
        if ctx.is_done("user_actions", row["id"], "user_actions"):
            t.already += 1
            continue
        attempt = attempts.get(str(row["attempt_id"]))
        action = str(row.get("action") or "").lower()
        edited = row.get("edited_text")
        if attempt is None or action not in UserActionKind.values:
            ctx.skip("user_actions", row, "sin intento importado o acción desconocida")
            continue
        if action == UserActionKind.EDIT and edited is None:
            ctx.skip(
                "user_actions", row, "una edición sin texto no cabe en la base nueva"
            )
            continue
        dropped = action != UserActionKind.EDIT and edited is not None
        made.append(
            (
                row,
                UserAction(
                    attempt_id=attempt,
                    action=action,
                    edited_text=edited if action == UserActionKind.EDIT else None,
                    **_created(row),
                ),
                dropped,
            )
        )
    _create(UserAction, [o for _, o, _ in made])
    for row, obj, adjusted in made:
        ctx.remember(
            "user_actions",
            row["id"],
            "user_actions",
            obj.pk,
            row=row if adjusted else None,
        )
        t.imported += 1


# -- 150: turn classifications ------------------------------------------------


def import_turns(ctx: ImportContext) -> None:
    t = ctx.table("turn_classifications")
    targets = profile_targets(ctx)
    messages = ctx.mapped("chat_messages", "chat_messages")
    rows = list(ctx.legacy.rows("turn_classifications"))
    t.read = len(rows)
    made: list[tuple[dict, TurnClassification, bool]] = []
    for row in rows:
        if ctx.is_done("turn_classifications", row["id"], "turn_classifications"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        if target is None:
            ctx.skip("turn_classifications", row, "sin perfil importado")
            continue
        message = (
            messages.get(str(row["message_id"])) if row.get("message_id") else None
        )
        path = str(row["path_taken"]).lower() if row.get("path_taken") else None
        bad_path = path is not None and path not in PathTaken.values
        tools = to_json(row.get("tools_called"))
        bad_tools = tools is not None and not isinstance(tools, list)
        made.append(
            (
                row,
                TurnClassification(
                    profile_id=target[0],
                    message_id=message,
                    message_text_hash=_text(row.get("message_text_hash"), 64)[0],
                    message_preview=row.get("message_preview") or "",
                    path_taken=None if bad_path else path,
                    rule_class=_text(row.get("rule_class"), 30)[0] or "other",
                    rule_matched=row.get("rule_matched"),
                    jev_called=to_bool(row.get("jev_called")),
                    jev_class=row.get("jev_class"),
                    jev_probs=to_json(row.get("jev_probs")),
                    jev_confidence=row.get("jev_confidence"),
                    jev_latency_ms=row.get("jev_latency_ms"),
                    jev_error=row.get("jev_error"),
                    final_class=_text(row.get("final_class"), 30)[0] or "other",
                    tools_called=None
                    if tools is None or bad_tools
                    else [str(x) for x in tools],
                    credits_spent=row.get("credits_spent"),
                    total_latency_ms=row.get("total_latency_ms"),
                    user_corrected=None
                    if row.get("user_corrected") is None
                    else to_bool(row["user_corrected"]),
                    timings=to_json(row.get("timings")),
                    **_created(row),
                ),
                bad_path
                or bad_tools
                or (row.get("message_id") is not None and message is None),
            )
        )
    _create(TurnClassification, [o for _, o, _ in made])
    for row, obj, adjusted in made:
        ctx.remember(
            "turn_classifications",
            row["id"],
            "turn_classifications",
            obj.pk,
            row=row if adjusted else None,
        )
        t.imported += 1


# -- 160: memory.md -----------------------------------------------------------


def import_memory(ctx: ImportContext) -> None:
    """``--memory-md`` is a path to the legacy file: the legacy agent had one memory, for one profile."""
    if not ctx.memory_md:
        return
    try:
        text = Path(ctx.memory_md).read_text(encoding="utf-8").strip()
    except OSError as exc:
        ctx.warn(f"memory.md no se importó: no se pudo leer ({exc.strerror})")
        return
    if not text:
        ctx.warn("memory.md no se importó: el archivo está vacío")
        return
    imported = sorted(set(ctx.mapped("profiles", "social_profiles").values()))
    if not imported:
        ctx.warn("memory.md no se importó: no hay ningún perfil importado")
        return
    profile = imported[0]
    if ProfileMemorySummary.objects.filter(profile_id=profile).exists():
        ctx.warn(f"memory.md no se importó: el perfil {profile} ya tiene un resumen")
        return
    ProfileMemorySummary.objects.create(profile_id=profile, summary_md=text)
    if len(imported) > 1:
        ctx.warn(f"memory.md se guardó en el perfil {profile}, el primero importado")


register(
    Importer(
        "intelligence_search_style",
        ("user_search_requests", "style_answers"),
        100,
        import_search_and_style,
    )
)
register(Importer("intelligence_voice", ("voice_profiles",), 110, import_voice))
register(
    Importer(
        "intelligence_taggings",
        ("own_post_analysis", "post_taggings"),
        120,
        import_taggings,
    )
)
register(
    Importer(
        "intelligence_reports",
        ("peer_frameworks", "niche_framework_reports"),
        130,
        import_reports,
    )
)
register(
    Importer(
        "intelligence_repurpose",
        ("repurpose_requests", "repurpose_attempts", "user_actions"),
        140,
        import_repurpose,
    )
)
register(Importer("intelligence_turns", ("turn_classifications",), 150, import_turns))
register(Importer("intelligence_memory", (), 160, import_memory))
