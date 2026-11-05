"""End-to-end competitor pipeline: fetch, baseline, winners, blind tagging, lift, synthesis, save.

Ported from ``lumi/legacy/app/services/peer_pipeline.py``. Rules that hold at every stage:

* winners are chosen by code against each account's own 4-week median, never by the model and
  never by a fixed bar (``winners.py``); thresholds are never lowered to fill a quota;
* the model only sees text (``extract.py``) and its failures become ``failed`` taggings;
* a report that cannot be supported is saved as ``insufficient_data`` or ``failed`` with **no
  frameworks** and an honest ``detail``; there is no canned payload;
* a platform that offers no way to read third-party posts (LinkedIn, Facebook) is reported as
  such; nothing is simulated.

Differences from the legacy: ``SocialData`` replaces the Xpoz client, ports replace SQLModel
sessions, and persistence errors are not swallowed (a failed write is a failed tool call).
Peer posts are stored *before* the report because ``framework_evidence`` points at them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from lumi_ai.agent.support import Completer
from lumi_ai.competitors.extract import (
    TAGGING_PROMPT_VERSION,
    from_record,
    lift_attributes,
    post_ref,
    tag_posts,
    to_record,
)
from lumi_ai.competitors.lift import LiftItem, build_lift_table
from lumi_ai.competitors.niche import slugify
from lumi_ai.competitors.schemas.peer import (
    NicheFrameworkReport,
    PeerConfig,
    PostStats,
    PostTagging,
)
from lumi_ai.competitors.synthesize import build_report
from lumi_ai.competitors.winners import (
    ScrapedPost,
    build_account_baseline,
    build_account_metrics,
    select_winners,
)
from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    BudgetExceeded,
    FrameworkIn,
    LiveDisabled,
    NicheReportIn,
    NicheReportOut,
    PeerPostIn,
    PeerPostOut,
    PeerPostStore,
    Platform,
    PostIn,
    ProviderAuthError,
    ReportStore,
    SocialData,
    SocialDataError,
    UnsupportedPlatform,
    VideoAnalysisStore,
    VideoAnalyzer,
)
from lumi_ai.video import VideoBatch, analyze_videos, for_tagging, persist, video_urls

log = logging.getLogger(__name__)

#: Errors that end the whole run: the next account would fail the same way.
_FATAL = (UnsupportedPlatform, LiveDisabled, ProviderAuthError)


@dataclass(frozen=True, slots=True)
class PipelineDeps:
    social: SocialData
    llm: Completer
    reports: ReportStore
    peer_posts: PeerPostStore
    config: AIConfig = field(default_factory=AIConfig)
    #: Called with the stored winner posts so the caller can index their vectors (sync, may block).
    index_peer_posts: Callable[[Sequence[PeerPostOut]], object] | None = None
    #: Video analysis (T10). ``None`` (``VIDEO_PROVIDER`` empty) leaves the pipeline exactly as it was.
    video: VideoAnalyzer | None = None
    video_store: VideoAnalysisStore | None = None


@dataclass(slots=True)
class PipelineResult:
    report: NicheFrameworkReport
    saved: NicheReportOut
    taggings: list[PostTagging]
    metrics: list[PostStats] = field(default_factory=list)
    scanned: dict[str, int] = field(
        default_factory=dict
    )  # handle -> usable posts fetched
    failures: list[str] = field(default_factory=list)
    detail: str | None = None
    stored_posts: list[PeerPostOut] = field(default_factory=list)
    video_analyzed: int = 0  # videos read now (cache hits are not counted)
    video_notes: list[str] = field(
        default_factory=list
    )  # one line per skipped or failed video


def scraped_from_post(post: PostIn, handle: str) -> ScrapedPost | None:
    """A usable peer post, or ``None`` when text or id is missing.

    ``is_pinned`` is unknown (no provider reports it), so it stays ``False`` and the report says so.
    """
    text = (post.text or "").strip()
    if not post.external_id or not text:
        return None
    created = post.published_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    m = post.metrics
    return ScrapedPost(
        post_id=post.external_id,
        handle=handle,
        created_at=created,
        text=text,
        views=m.views,
        likes=m.likes,
        replies=m.comments,
        reposts=m.shares,
        quotes=m.quotes,
        bookmarks=m.bookmarks,
        url=post.url,
        is_reply=post.kind == "reply",
        is_repost=post.kind == "retweet",
    )


def _normalize_handles(handles: Sequence[str], limit: int) -> list[str]:
    seen: dict[str, None] = {}
    for raw in handles:
        handle = str(raw).strip().lstrip("@").lower()
        if handle:
            seen.setdefault(handle)
    return list(seen)[:limit]


def budget_message(where: str, exc: BudgetExceeded) -> str:
    """Say plainly that the run budget is too small, with the numbers the adapter gave.

    A platform whose single run costs more than the budget (Xpoz Instagram: 12 credits
    against the default 10) must surface as "budget insufficient", never as a silent empty run.
    """
    figures = ""
    if exc.budget is not None:
        spent = exc.spent if exc.spent is not None else 0
        figures = f" ({spent} of {exc.budget} credits spent)"
    extra = f": {exc}" if str(exc) else ""
    return (
        f"credit budget insufficient before {where}{figures}{extra}; "
        "raise XPOZ_RUN_CREDIT_BUDGET or analyse fewer accounts"
    )


async def _fetch(
    deps: PipelineDeps,
    platform: Platform,
    handles: list[str],
    now: datetime,
) -> tuple[
    dict[str, list[ScrapedPost]], dict[str, PostIn], list[str], list[str], str | None
]:
    """Fetch every account. Returns posts by handle, raw posts by id, failures, warnings, fatal."""
    posts_by_handle: dict[str, list[ScrapedPost]] = {}
    raw_by_key: dict[str, PostIn] = {}
    failures: list[str] = []
    warnings: list[str] = []
    since = now - timedelta(days=PeerConfig.LOOKBACK_DAYS)
    for handle in handles:
        try:
            posts = await deps.social.fetch_user_posts(
                platform, handle, since, PeerConfig.SCAN_POSTS_PER_ACCOUNT
            )
        except BudgetExceeded as exc:
            warnings.append(budget_message(f"@{handle}", exc))
            break
        except _FATAL as exc:
            return (
                posts_by_handle,
                raw_by_key,
                failures,
                warnings,
                f"{exc}" or type(exc).__name__,
            )
        except SocialDataError as exc:
            log.warning("peer fetch failed for @%s: %s", handle, exc)
            failures.append(f"@{handle}: {exc or type(exc).__name__}")
            continue
        usable = [s for p in posts if (s := scraped_from_post(p, handle))]
        if not usable:
            failures.append(f"@{handle}: no usable posts (missing text)")
            continue
        for p in posts:
            raw_by_key[f"{handle}:{p.external_id}"] = p
        posts_by_handle[handle] = usable
    return posts_by_handle, raw_by_key, failures, warnings, None


def _frameworks(
    report: NicheFrameworkReport, platform: Platform, stored_ids: set[str]
) -> tuple[FrameworkIn, ...]:
    if report.synthesis is None:
        return ()
    reported = {
        f"{r.dimension}={r.value}": r.lift
        for r in report.lift_table
        if r.status == "reported" and r.lift is not None
    }
    out: list[FrameworkIn] = []
    for f in report.synthesis.winning_frameworks:
        key = slugify(f.name) or f"framework-{len(out) + 1}"
        lifts = [reported[k] for k in f.supporting_lift_rows if k in reported]
        out.append(
            FrameworkIn(
                name=key,
                title=f.name,
                description=f"{f.hook_formula} | {f.when_to_use}",
                evidence_post_refs=tuple(
                    post_ref(platform, i)
                    for i in f.evidence_post_ids
                    if i in stored_ids
                ),
                lift=max(lifts) if lifts else None,
                confidence=f.confidence,
                payload={
                    "key": key,
                    "title": f.name,
                    "structure": f.structure,
                    "hook_formula": f.hook_formula,
                    "when_to_use": f.when_to_use,
                    "supporting_lift_rows": f.supporting_lift_rows,
                },
            )
        )
    return tuple(out)


async def run_peer_pipeline(
    deps: PipelineDeps,
    *,
    profile_id: int,
    platform: Platform,
    niche: str,
    niche_key: str | None,
    handles: Sequence[str],
    now: datetime | None = None,
) -> PipelineResult:
    """Analyse up to ``config.peer_max_accounts`` accounts and store the report."""
    now = now or datetime.now(UTC)
    cfg = deps.config
    wanted = _normalize_handles(handles, cfg.peer_max_accounts)

    posts_by_handle, raw_by_key, failures, warnings, fatal = await _fetch(
        deps, platform, wanted, now
    )
    scanned = {h: len(p) for h, p in posts_by_handle.items()}

    baselines = {
        h: build_account_baseline(h, posts, now=now)
        for h, posts in posts_by_handle.items()
    }
    metrics_by_handle = {
        h: build_account_metrics(posts, baselines[h], now=now)
        for h, posts in posts_by_handle.items()
    }
    all_metrics = [m for rows in metrics_by_handle.values() for m in rows]
    selection = select_winners(metrics_by_handle, baselines, now=now)
    winner_ids = {w.post_id for w in selection.winners}

    # Winners first, so the cost cap never drops them.
    ordered = sorted(all_metrics, key=lambda m: m.post_id not in winner_ids)
    to_tag = ordered[: cfg.peer_max_posts_to_tag]
    refs = [post_ref(platform, m.post_id) for m in to_tag]
    cached: dict[str, PostTagging] = {}
    if refs:
        for record in await deps.reports.cached_taggings(
            profile_id, refs, TAGGING_PROMPT_VERSION
        ):
            tagging = from_record(record, platform)
            if tagging is not None and tagging.status == "ok":
                cached[tagging.post_id] = tagging
    untagged = [m for m in to_tag if m.post_id not in cached]
    video_batch, video_by_post = await _read_videos(deps, untagged, raw_by_key)
    fresh = await tag_posts(deps.llm, untagged, video_by_post)
    taggings = [*cached.values(), *fresh]
    if fresh:
        records = [r for t in fresh if (r := to_record(t, platform))]
        await deps.reports.save_taggings(profile_id, records)

    by_id = {m.post_id: m for m in all_metrics}
    items = [
        LiftItem(
            attributes=attrs,
            is_winner=pid in winner_ids,
            outlier_views=by_id[pid].outlier_views,
        )
        for pid, attrs in lift_attributes(all_metrics, taggings).items()
        if pid in by_id
    ]
    report = build_report(
        niche=niche,
        accounts=list(baselines.values()),
        selection=selection,
        taggings=taggings,
        lift_rows=build_lift_table(items),
        now=now,
    )

    detail: str | None = None
    warn = [*warnings, *selection.warnings]
    if fatal is not None:
        report = report.model_copy(update={"status": "failed"})
        detail = f"provider refused the run: {fatal}"
    elif not posts_by_handle:
        if any(w.startswith("credit budget") for w in warnings):
            report = report.model_copy(update={"status": "insufficient_data"})
            detail = "; ".join(warnings)
        else:
            report = report.model_copy(update={"status": "failed"})
            detail = "no account could be read: " + "; ".join(
                failures or ["no handles"]
            )
    elif report.status == "insufficient_data":
        detail = selection.insufficient_reason
        if warnings:
            detail = "; ".join([detail or "", *warnings]).strip("; ")
    elif report.status == "failed":
        detail = "blind tagging produced no usable analysis: " + (
            next((t.validation_error for t in taggings if t.validation_error), None)
            or "no posts were tagged"
        )
    report = report.model_copy(update={"warnings": [*report.warnings, *warn]})

    # Peer posts first: framework_evidence rows point at them.
    stored: list[PeerPostOut] = []
    if to_tag:
        peer_posts = [
            _peer_post(
                platform, m, raw_by_key.get(f"{m.handle}:{m.post_id}"), niche_key
            )
            for m in to_tag
        ]
        stored = await deps.peer_posts.save_peer_posts(profile_id, peer_posts)
    stored_ext = {p.external_id for p in stored}

    frameworks = _frameworks(report, platform, stored_ext)
    saved = await deps.reports.save_report(
        profile_id,
        NicheReportIn(
            niche_key=niche_key,
            status=report.status,
            posts_analyzed=report.posts_analyzed,
            winner_count=len(report.winner_post_ids),
            payload=report.model_dump(mode="json"),
            frameworks=frameworks,
            detail=detail,
            query=niche,
            peers_analyzed=len(posts_by_handle),
            peer_handles={platform: tuple(posts_by_handle)} if posts_by_handle else {},
        ),
    )

    winner_ext = set(report.winner_post_ids)
    winner_rows = [p for p in stored if p.external_id in winner_ext]
    if video_batch is not None:
        await persist(
            video_batch,
            deps.video_store,
            provider=_video_provider(deps),
            model=deps.config.video_model,
        )

    if deps.index_peer_posts is not None and winner_rows:
        await asyncio.to_thread(deps.index_peer_posts, winner_rows)

    return PipelineResult(
        report=report,
        saved=saved,
        taggings=taggings,
        metrics=all_metrics,
        scanned=scanned,
        failures=failures,
        detail=detail,
        stored_posts=stored,
        video_analyzed=len(video_batch.fresh) if video_batch else 0,
        video_notes=video_batch.notes() if video_batch else [],
    )


def _video_provider(deps: PipelineDeps) -> str:
    return getattr(deps.video, "provider", None) or (deps.config.video_provider or "")


async def _read_videos(
    deps: PipelineDeps,
    posts: Sequence[PostStats],
    raw_by_key: Mapping[str, PostIn],
) -> tuple[VideoBatch | None, dict[str, dict[str, object]]]:
    """Analyse the videos of the posts about to be tagged. ``(None, {})`` when video is off.

    Winners come first in ``posts`` so the per-run cap never drops them. The reading is an extra
    field of the blind tagging (``for_tagging`` carries no views or winner flags).
    """
    if deps.video is None:
        return None, {}
    urls_by_post: dict[str, list[str]] = {}
    contexts: dict[str, str] = {}
    for m in posts:
        raw = raw_by_key.get(f"{m.handle}:{m.post_id}")
        urls, _ = video_urls(raw.media or ()) if raw is not None else ([], [])
        if urls:
            urls_by_post[m.post_id] = urls[
                :1
            ]  # one video per post is enough to read its hook
            contexts[urls[0]] = m.text
    batch = await analyze_videos(
        [u for urls in urls_by_post.values() for u in urls],
        deps.video,
        store=deps.video_store,
        config=deps.config,
        provider=_video_provider(deps),
        contexts=contexts,
    )
    by_post = {
        post_id: for_tagging(batch.results[urls[0]])
        for post_id, urls in urls_by_post.items()
        if urls[0] in batch.results
    }
    return batch, by_post


def _peer_post(
    platform: Platform, m: PostStats, raw: PostIn | None, niche_key: str | None
) -> PeerPostIn:
    kwargs = {}
    if raw is not None:
        kwargs = {
            "metrics": raw.metrics,
            "media": raw.media,
            "author_avatar_url": raw.author_avatar_url,
        }
    return PeerPostIn(
        platform=platform,
        external_id=m.post_id,
        author_handle=m.handle,
        text=m.text,
        published_at=m.created_at,
        url=m.url,
        niche_key=niche_key,
        **kwargs,
    )
