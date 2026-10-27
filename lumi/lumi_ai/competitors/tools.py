"""Agent tools of the competitor analysis: discover and extract frameworks, advice, pasted post,
own lift and niche trends.

``build`` returns the tools whose ports exist; the rest are simply not offered. Every tool answers
with what it actually read: a missing report, a refused provider or a thin sample come back as an
``error`` or an honest ``status``, never as filler. The profile comes from the turn
(``ToolContext``), never from the model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, get_args

from lumi_ai.competitors.extract import post_ref, tag_posts
from lumi_ai.competitors.handles import (
    authors_of,
    known_pictures,
    remember_authors,
    remember_scanned,
)
from lumi_ai.competitors.niche import make_niche_key, slugify
from lumi_ai.competitors.own import compute_own_lift
from lumi_ai.competitors.pipeline import (
    PipelineDeps,
    budget_message,
    run_peer_pipeline,
)
from lumi_ai.competitors.ranking import framework_key, rank_frameworks
from lumi_ai.ports import (
    BudgetExceeded,
    Embedder,
    FrameworkOut,
    HandleBook,
    KnownHandle,
    LiveDisabled,
    MatchStore,
    PeerPostIn,
    PostIn,
    PostStore,
    ProfileStore,
    ProviderAuthError,
    SocialDataError,
    UnsupportedPlatform,
)
from lumi_ai.ports import Platform as PlatformType
from lumi_ai.rag.retrieval import Retriever
from lumi_ai.tools.registry import ToolContext, ToolSpec

PLATFORMS: tuple[str, ...] = get_args(PlatformType)
DEFAULT_PLATFORM: PlatformType = "x"
DEFAULT_MIN_LIKES = 20
TREND_POSTS_PER_HANDLE = 10
EXAMPLE_TEXT_CHARS = 400
_FATAL = (UnsupportedPlatform, LiveDisabled, ProviderAuthError)

_PLATFORM_PARAM = {
    "type": "string",
    "enum": list(PLATFORMS),
    "description": "Network to read. Defaults to the profile's main network.",
}


@dataclass(frozen=True, slots=True)
class CompetitorServices:
    pipeline: PipelineDeps
    profiles: ProfileStore
    posts: PostStore | None = None
    matches: MatchStore | None = None
    embedder: Embedder | None = None
    retriever: Retriever | None = None
    handles: HandleBook | None = None


def _framework_view(fw: FrameworkOut, relevance: float | None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "key": framework_key(fw),
        "title": fw.title,
        "structure": fw.payload.get("structure"),
        "hook_formula": fw.payload.get("hook_formula"),
        "when_to_use": fw.payload.get("when_to_use"),
        "lift": fw.lift,
        "confidence": fw.confidence,
        "evidence_post_refs": list(fw.evidence_post_refs),
    }
    if relevance is not None:
        view["relevance"] = round(relevance, 3)
    return view


def _int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _clean_handles(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    seen: dict[str, None] = {}
    for h in raw or []:
        name = str(h).strip().lstrip("@").lower()
        if name:
            seen.setdefault(name)
    return list(seen)


def _refusal(exc: SocialDataError) -> dict[str, Any]:
    return {"error": f"{type(exc).__name__}: {exc}"}


def build(services: CompetitorServices) -> list[ToolSpec]:
    s = services
    reports = s.pipeline.reports

    async def _platform(ctx: ToolContext, platform: str | None) -> PlatformType | None:
        if platform:
            return platform if platform in PLATFORMS else None  # type: ignore[return-value]
        info = await s.profiles.get_profile(ctx.profile_id)
        return info.primary_platform if info else DEFAULT_PLATFORM

    # -- discover_and_extract_niche_frameworks ------------------------------

    async def discover(
        ctx: ToolContext,
        query: str,
        platform: str | None = None,
        geo_scope: str | None = None,
        handles: list[str] | None = None,
    ) -> dict[str, Any]:
        plat = await _platform(ctx, platform)
        if plat is None:
            return {"error": f"unknown platform {platform!r}; use one of {PLATFORMS}"}
        try:
            niche_key = make_niche_key(query, geo_scope)
        except ValueError as exc:
            return {"error": str(exc)}
        cfg = ctx.config
        deps = replace(s.pipeline, config=cfg)
        info = await s.profiles.get_profile(ctx.profile_id)
        own = (info.handle if info else "").lstrip("@").lower()

        chosen = [h for h in _clean_handles(handles) if h != own]
        discovered = False
        if not chosen:
            try:
                found = await s.pipeline.social.search_posts(
                    plat, query, cfg.peer_discovery_posts
                )
            except BudgetExceeded as exc:
                return {"error": budget_message(f"searching {query!r} on {plat}", exc)}
            except SocialDataError as exc:
                return _refusal(exc)
            # Everyone the search surfaced is worth remembering, not only the peers it picks.
            await remember_authors(s.handles, plat, authors_of(found))
            chosen = _rank_authors(found, exclude=own, limit=cfg.peer_max_accounts)
            discovered = True
            if not chosen:
                return {
                    "error": f"the search for {query!r} on {plat} returned no accounts to analyse",
                }
        result = await run_peer_pipeline(
            deps,
            profile_id=ctx.profile_id,
            platform=plat,
            niche=query,
            niche_key=niche_key,
            handles=chosen,
        )
        await remember_scanned(s.handles, plat, list(result.scanned))
        out: dict[str, Any] = {
            "status": result.saved.status,
            "report_id": result.saved.id,
            "niche_key": niche_key,
            "platform": plat,
            "handles": chosen,
            "handles_from_search": discovered,
            "peers_analyzed": result.saved.peers_analyzed,
            "posts_analyzed": result.saved.posts_analyzed,
            "winner_count": result.saved.winner_count,
            "frameworks": [_framework_view(f, None) for f in result.saved.frameworks],
            "warnings": list(result.report.warnings),
            "scanned_handles": result.scanned,
        }
        if result.detail:
            out["detail"] = result.detail
        if result.failures:
            out["failed_handles"] = result.failures
        if result.video_analyzed or result.video_notes:
            out["videos_analyzed"] = result.video_analyzed
            if result.video_notes:
                out["video_notes"] = result.video_notes
        return out

    # -- get_peer_advice ----------------------------------------------------

    async def advice(
        ctx: ToolContext, topic: str, platform: str | None = None
    ) -> dict[str, Any]:
        report = await reports.latest_report(ctx.profile_id)
        if report is None:
            return {
                "error": "no niche analysis yet. Run discover_and_extract_niche_frameworks first.",
            }
        head = {
            "report_id": report.id,
            "status": report.status,
            "query": report.query,
            "niche_key": report.niche_key,
            "peers_analyzed": report.peers_analyzed,
            "analyzed_at": report.created_at.isoformat(),
        }
        if report.status != "ok":
            return {
                **head,
                "detail": report.detail,
                "frameworks": [],
                "examples": [],
                "error": f"the last niche analysis is {report.status}; there is no advice to give from it",
            }
        limit = ctx.config.peer_advice_max_items
        views = [_framework_view(f, None) for f in report.frameworks]
        if s.embedder is not None:
            ranked = await rank_frameworks(s.embedder, topic, report.frameworks)
            if ranked:
                views = [_framework_view(f, score) for f, score in ranked]
        examples: list[dict[str, Any]] = []
        if s.retriever is not None and topic.strip():
            for hit in await s.retriever.similar_peer_posts(
                ctx.profile_id,
                topic,
                limit,
                platform=platform,
                niche_key=report.niche_key,
            ):
                p = hit.item
                examples.append(
                    {
                        "author": p.author_handle,
                        "text": p.text[:EXAMPLE_TEXT_CHARS],
                        "url": p.url,
                        "views": p.metrics.views,
                        "likes": p.metrics.likes,
                        "distance": round(hit.distance, 3),
                    }
                )
        return {**head, "frameworks": views[:limit], "examples": examples}

    # -- analyze_pasted_post ------------------------------------------------

    async def analyze_pasted(
        ctx: ToolContext, text: str, platform: str | None = None
    ) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            return {"error": "no post text to analyse"}
        plat = await _platform(ctx, platform)
        if plat is None:
            return {"error": f"unknown platform {platform!r}; use one of {PLATFORMS}"}
        digest = hashlib.sha256(body.encode()).hexdigest()[:10]
        pasted = _Pasted(post_id=f"pasted-{digest}", text=body)
        (tagging,) = await tag_posts(s.pipeline.llm, [pasted])
        if tagging.status != "ok" or tagging.analysis is None:
            return {
                "error": f"could not analyse the post: {tagging.validation_error or tagging.status}",
            }
        analysis = tagging.analysis
        out: dict[str, Any] = {
            "post_ref": post_ref(plat, pasted.post_id),
            "analysis": analysis.model_dump(mode="json"),
            "primary_framework": analysis.body.primary_framework,
        }
        if tagging.framework_guess:
            out["framework_guess"] = tagging.framework_guess
        report = await reports.latest_report(ctx.profile_id)
        if report is None or report.status != "ok":
            out["niche_comparison"] = (
                "no niche analysis to compare against"
                if report is None
                else f"the last niche analysis is {report.status}"
            )
            return out
        key = slugify(analysis.body.primary_framework.replace("_", " "))
        match = next(
            (f for f in report.frameworks if slugify(framework_key(f)) == key), None
        )
        out["niche_comparison"] = {
            "report_id": report.id,
            "matches_niche_framework": match is not None,
            "framework": _framework_view(match, None) if match else None,
            "niche_frameworks": [framework_key(f) for f in report.frameworks],
        }
        return out

    # -- own lift -----------------------------------------------------------

    async def own_lift(ctx: ToolContext, platform: str | None = None) -> dict[str, Any]:
        assert s.posts is not None
        info = await s.profiles.get_profile(ctx.profile_id)
        if info is None:
            return {"error": f"no profile {ctx.profile_id}"}
        plat = await _platform(ctx, platform)
        if plat is None:
            return {"error": f"unknown platform {platform!r}; use one of {PLATFORMS}"}
        posts = await s.posts.list_posts(ctx.profile_id, platform=plat, limit=200)
        lift = compute_own_lift(posts, info.handle.lstrip("@"))
        return {
            "status": lift.status,
            "platform": plat,
            "n_eligible": lift.n_eligible,
            "n_winners": lift.n_winners,
            "winner_post_ids": list(lift.winner_post_ids),
            "baseline": lift.baseline.model_dump(mode="json"),
            "lift_rows": [r.model_dump(mode="json") for r in lift.lift_rows],
            "dimensions_covered": list(lift.dimensions_covered),
            "reason": lift.reason,
            "warnings": list(lift.warnings),
        }

    # -- check_niche_trends -------------------------------------------------

    async def trends(
        ctx: ToolContext,
        handles: list[str] | None = None,
        min_likes: int = DEFAULT_MIN_LIKES,
        platform: str | None = None,
    ) -> dict[str, Any]:
        assert s.matches is not None
        plat = await _platform(ctx, platform)
        if plat is None:
            return {"error": f"unknown platform {platform!r}; use one of {PLATFORMS}"}
        threshold = _int(min_likes, DEFAULT_MIN_LIKES)
        niche = await s.profiles.get_niche(ctx.profile_id)
        wanted = _clean_handles(handles) or _clean_handles(
            niche.tracked_handles.get(plat, ()) if niche else ()
        )
        if not wanted:
            return {
                "error": f"no accounts to check on {plat}: pass handles or track some in the profile's niche",
            }
        niche_key = niche.niche_key if niche else None
        found: list[dict[str, Any]] = []
        new_matches = 0
        failures: list[str] = []
        scanned: dict[str, int] = {}
        authors: dict[str, KnownHandle] = {}
        stopped: str | None = None
        for handle in wanted[: ctx.config.peer_max_accounts]:
            try:
                posts = await s.pipeline.social.fetch_user_posts(
                    plat, handle, None, TREND_POSTS_PER_HANDLE
                )
            except BudgetExceeded as exc:
                stopped = budget_message(f"@{handle}", exc)
                break
            except _FATAL as exc:
                return {**_refusal(exc), "scanned_handles": scanned}
            except SocialDataError as exc:
                failures.append(f"@{handle}: {exc}")
                continue
            scanned[handle] = len(posts)
            authors_of(posts, handle, into=authors)
            viral = [p for p in posts if _is_viral(p, threshold)]
            if not viral:
                continue
            stored = await s.pipeline.peer_posts.save_peer_posts(
                ctx.profile_id,
                [_peer_post(p, handle, niche_key) for p in viral],
            )
            for row in stored:
                fresh = await s.matches.record_listening_match(ctx.profile_id, row.id)
                if fresh:
                    new_matches += 1
                    found.append(
                        {
                            "author": row.author_handle,
                            "text": row.text[:EXAMPLE_TEXT_CHARS],
                            "url": row.url,
                            "likes": row.metrics.likes,
                            "views": row.metrics.views,
                            "avatar_url": row.author_avatar_url or "",
                        }
                    )
        # The accounts read, and every author the posts surfaced (viral or not).
        await remember_scanned(s.handles, plat, list(scanned))
        await remember_authors(s.handles, plat, authors)
        missing = [f["author"] for f in found if not f["avatar_url"]]
        if missing:
            pictures = await known_pictures(s.handles, plat, missing)
            for item in found:
                item["avatar_url"] = item["avatar_url"] or pictures.get(
                    str(item["author"]).lower(), ""
                )
        out: dict[str, Any] = {
            "platform": plat,
            "min_likes": threshold,
            "new_matches_found": new_matches,
            "viral_posts": found,
            "scanned_handles": scanned,
        }
        if failures:
            out["failed_handles"] = failures
        if stopped:
            out["warning"] = stopped
        if not scanned and (failures or stopped):
            out["error"] = (
                "no account could be read, so nothing is known about the niche right now: "
                + (stopped or failures[0])
            )
        return out

    tools = [
        ToolSpec(
            name="discover_and_extract_niche_frameworks",
            description=(
                "Find the accounts that write about a niche (a search, or the handles given), read their "
                "recent posts, pick the winners against each account's own median and extract the "
                "structures behind them. Saves a niche report. Costs provider credits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Niche, e.g. 'founder startup' or 'lagos tech builder'.",
                    },
                    "platform": _PLATFORM_PARAM,
                    "geo_scope": {
                        "type": "string",
                        "description": "Two-letter country code, or leave out for global.",
                    },
                    "handles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Accounts to analyse instead of searching.",
                    },
                },
                "required": ["query"],
            },
            handler=discover,
            cost="credits",
            side_effects="writes_index",
        ),
        ToolSpec(
            name="get_peer_advice",
            description=(
                "Read the latest niche analysis and return the frameworks that fit a topic, best first, "
                "with a few real peer posts as examples. Reads only; run the discovery tool first if "
                "there is no analysis."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "What the post is about.",
                    },
                    "platform": _PLATFORM_PARAM,
                },
                "required": ["topic"],
            },
            handler=advice,
            cost="free",
        ),
        ToolSpec(
            name="analyze_pasted_post",
            description=(
                "Analyse the structure of a post the user pasted (hook, body framework, call to action) "
                "and say whether it matches a framework from their niche. Fetches nothing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The post text, as pasted.",
                    },
                    "platform": _PLATFORM_PARAM,
                },
                "required": ["text"],
            },
            handler=analyze_pasted,
            cost="llm",
            cache_ttl=0,  # the comparison depends on the niche report, which can change between calls
        ),
    ]
    if s.posts is not None:
        tools.append(
            ToolSpec(
                name="get_own_lift",
                description=(
                    "Which of the user's own posts beat their own median views, and which formats "
                    "carry them. Reads stored posts; fetches nothing."
                ),
                parameters={
                    "type": "object",
                    "properties": {"platform": _PLATFORM_PARAM},
                    "required": [],
                },
                handler=own_lift,
                cost="free",
            )
        )
    if s.matches is not None:
        tools.append(
            ToolSpec(
                name="check_niche_trends",
                description=(
                    "Read recent posts of niche accounts and keep the ones above a like threshold as "
                    "matches the user can repurpose. Defaults to the accounts tracked in the profile's niche. "
                    "Costs provider credits."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "handles": {"type": "array", "items": {"type": "string"}},
                        "min_likes": {
                            "type": "integer",
                            "description": f"Likes needed to count as viral (default {DEFAULT_MIN_LIKES}).",
                        },
                        "platform": _PLATFORM_PARAM,
                    },
                    "required": [],
                },
                handler=trends,
                cost="credits",
                side_effects="writes_db",
            )
        )
    return tools


@dataclass(frozen=True, slots=True)
class _Pasted:
    post_id: str
    text: str
    handle: str = "pasted"
    thread_texts: tuple[str, ...] = ()


def _is_viral(post: PostIn, min_likes: int) -> bool:
    likes = post.metrics.likes
    return bool(
        post.external_id
        and (post.text or "").strip()
        and likes is not None
        and likes >= min_likes
        and post.kind in (None, "original")
    )


def _peer_post(post: PostIn, handle: str, niche_key: str | None) -> PeerPostIn:
    return PeerPostIn(
        platform=post.platform,
        external_id=post.external_id,
        author_handle=(post.author_handle or handle).lstrip("@").lower(),
        text=post.text.strip(),
        published_at=post.published_at,
        url=post.url,
        metrics=post.metrics,
        media=post.media,
        niche_key=niche_key,
        author_avatar_url=post.author_avatar_url,
    )


def _rank_authors(posts: list[PostIn], *, exclude: str, limit: int) -> list[str]:
    """Authors a search surfaced, most posts first, then most likes. The user's own handle is out."""
    stats: dict[str, list[int]] = {}
    for p in posts:
        name = (p.author_handle or "").lstrip("@").lower()
        if not name or name == exclude:
            continue
        row = stats.setdefault(name, [0, 0])
        row[0] += 1
        row[1] += p.metrics.likes or 0
    ranked = sorted(stats, key=lambda n: (-stats[n][0], -stats[n][1], n))
    return ranked[:limit]
