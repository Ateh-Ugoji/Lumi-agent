"""End-to-end peer pipeline: fetch -> baseline -> winners -> blind tagging ->
lift -> synthesis -> persistence (Prompts 1-3 of the peer-framework upgrade).

Replaces the old path ("impressions >= 1000 -> posts[:20] -> LLM -> canned
frameworks"). Rules that hold at every stage:

- winners are chosen by code against each account's own 4-week median, never by
  the LLM and never by a fixed bar;
- the LLM only sees text (see `analysis.extract`), and its failures produce
  `failed` taggings, never invented analyses;
- a report that cannot be supported comes back `insufficient_data`/`failed` with
  **no frameworks** — this pipeline has no canned payload;
- persistence is best-effort: an analytics write never fails the tool call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import neatlogs

from app import database
from app.analysis.extract import TAGGING_PROMPT_VERSION, lift_attributes, tag_posts
from app.analysis.lift import LiftItem, build_lift_table
from app.analysis.synthesize import build_report
from app.analysis.winners import (
    ScrapedPost,
    WinnerSelection,
    build_account_baseline,
    build_account_metrics,
    select_winners,
)
from app.schemas.peer import (
    NicheFrameworkReport,
    PeerConfig,
    PostMetrics,
    PostTagging,
)
from app.services import peer_store

log = logging.getLogger(__name__)

# Cost guards: Xpoz charges per lookup and each tagged batch costs an LLM call.
MAX_ACCOUNTS_TO_SCAN = 8
MAX_POSTS_TO_TAG = 80  # 10 batches of PeerConfig.BATCH_SIZE
XPOZ_PAGE_SIZE = 20  # the user-live endpoint returns 20-post pages


@dataclass
class PipelineResult:
    report: NicheFrameworkReport
    taggings: list[PostTagging]
    metrics: list[PostMetrics] = field(default_factory=list)  # every buildable post
    scanned: dict[str, int] = field(default_factory=dict)  # handle -> posts fetched
    failures: list[str] = field(default_factory=list)
    report_id: int | None = None


def winner_post_dicts(result: PipelineResult) -> list[dict]:
    """Winner posts in the raw-Xpoz shape `framework_corpus.upsert_peer_posts` expects.

    The bridge keeps the Chroma `peer_posts` index fed without re-fetching: the
    metadata keys (`id`/`authorUsername`/`impressionCount`) are the ones that
    legacy reader already consumes.
    """
    winners = set(result.report.winner_post_ids)
    return [
        {
            "id": m.post_id,
            "text": m.text,
            "authorUsername": m.handle,
            "impressionCount": m.views,
        }
        for m in result.metrics
        if m.post_id in winners and m.text
    ]


def _created_at(value: object) -> datetime | None:
    """Parse a tweet timestamp; None when it is missing/unparseable.

    Unlike the ingest fallback (which defaults to now), an undated post is
    *dropped*: the 24h age rule and the 4-week window cannot be honoured without
    a real date, and guessing one would fake eligibility.
    """
    if not value:
        return None
    try:
        # 3.11+ fromisoformat parses a trailing "Z" directly.
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _as_int(value: object) -> int | None:
    """int or None — a missing metric stays missing, never 0."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_scraped(handle: str, tweets: list[dict]) -> list[ScrapedPost]:
    clean_handle = handle.lstrip("@").lower()
    out: list[ScrapedPost] = []
    for tweet in tweets:
        post_id = str(tweet.get("id") or "")
        text = (tweet.get("text") or "").strip()
        created_at = _created_at(tweet.get("createdAt"))
        if not post_id or not text or created_at is None:
            continue
        author = str(tweet.get("authorUsername") or clean_handle).lstrip("@")
        out.append(
            ScrapedPost(
                post_id=post_id,
                handle=clean_handle,
                created_at=created_at,
                text=text,
                views=_as_int(tweet.get("impressionCount")),
                likes=_as_int(tweet.get("likeCount")),
                replies=_as_int(tweet.get("replyCount")),
                reposts=_as_int(tweet.get("retweetCount")),
                quotes=_as_int(tweet.get("quoteCount")),
                bookmarks=_as_int(tweet.get("bookmarkCount")),
                url=f"https://x.com/{author}/status/{post_id}",
                is_reply=bool(tweet.get("replyToTweetId")),
                is_repost=bool(tweet.get("isRetweet")),
                # `isPinned` is not in Xpoz's allowed fields — unknown, not False-by-luck:
                # pinned posts simply cannot be detected yet (docs/xpoz_capabilities.md).
                is_pinned=False,
            )
        )
    return out


async def fetch_account_posts(client, handle: str, limit: int) -> list[ScrapedPost]:
    """Paginated user-live fetch for one account (the endpoint pages 20 at a time)."""
    collected: list[ScrapedPost] = []
    cursor: str | None = None
    while len(collected) < limit:
        page, cursor, has_more = await client.get_user_live_posts_page(
            handle, limit=XPOZ_PAGE_SIZE, cursor=cursor
        )
        collected.extend(_to_scraped(handle, page))
        if not has_more or not cursor:
            break
    return collected[:limit]


def legacy_payload_from_report(report: NicheFrameworkReport, query: str) -> dict:
    """Bridge shape for `peer_frameworks` / Chroma / `get_peer_advice`.

    Built strictly from the report: no canned content, and `percentage_of_posts`
    stays 0 with the reason spelled out because the report does not measure it.
    """
    synthesis = report.synthesis
    frameworks = []
    pillars = []
    if synthesis is not None:
        frameworks = [
            {
                "name": f.name,
                "structure": f.structure,
                "hook_formula": f.hook_formula,
                "engagement_driver": f.when_to_use,
                "evidence_post_ids": f.evidence_post_ids,
                "confidence": f.confidence,
            }
            for f in synthesis.winning_frameworks
        ]
        pillars = [
            {
                "pillar_name": name,
                "percentage_of_posts": 0,  # not measured by the lift table — never invented
                "description": "reported pillar: lifted among winners vs the account baselines",
                "why_it_works": "appears more often in winners than in those accounts' baseline posts",
            }
            for name in synthesis.content_pillars
        ]
    return {
        "niche_title": report.niche or query,
        "analyzed_peers_count": len(report.accounts),
        "top_peer_handles": [f"@{a.handle}" for a in report.accounts],
        "content_pillars": pillars,
        "winning_frameworks": frameworks,
        "pacing_and_format_rules": {},
        "actionable_post_prompts": [],
        "report_status": report.status,
        "winner_post_ids": report.winner_post_ids,
        "report_id": None,
        "warnings": list(synthesis.warnings) if synthesis else [],
    }


@neatlogs.span(kind="WORKFLOW", name="peer_pipeline")
async def run_peer_pipeline(
    *,
    profile_id: int,
    niche: str,
    handles: list[str],
    client,
    persist: bool = True,
) -> PipelineResult:
    """Run the whole pipeline over up to `MAX_ACCOUNTS_TO_SCAN` accounts."""
    now = datetime.now(UTC)
    scanned: dict[str, int] = {}
    failures: list[str] = []
    posts_by_handle: dict[str, list[ScrapedPost]] = {}

    for raw_handle in handles[:MAX_ACCOUNTS_TO_SCAN]:
        handle = raw_handle.lstrip("@").strip()
        if not handle:
            continue
        try:
            posts = await fetch_account_posts(client, handle, PeerConfig.SCAN_POSTS_PER_ACCOUNT)
        except Exception as exc:  # noqa: BLE001 — one bad account must not sink the run
            log.warning("peer fetch failed for @%s: %s", handle, exc)
            failures.append(f"@{handle}: {exc}")
            continue
        if posts:
            posts_by_handle[handle.lower()] = posts
            scanned[handle.lower()] = len(posts)
        else:
            failures.append(f"@{handle}: no usable posts (missing dates/text)")

    baselines = {
        handle: build_account_baseline(handle, posts, now=now)
        for handle, posts in posts_by_handle.items()
    }
    metrics_by_handle = {
        handle: build_account_metrics(posts, baselines[handle], now=now)
        for handle, posts in posts_by_handle.items()
    }
    all_metrics: list[PostMetrics] = [m for rows in metrics_by_handle.values() for m in rows]
    selection: WinnerSelection = select_winners(metrics_by_handle, baselines, now=now)
    winner_ids = {w.post_id for w in selection.winners}

    # Blind tagging: winners first so a cost cap never drops them.
    ordered = sorted(all_metrics, key=lambda m: m.post_id not in winner_ids)
    to_tag = ordered[:MAX_POSTS_TO_TAG]
    cached: dict[str, PostTagging] = {}
    if persist and to_tag:
        try:
            async with database.session_scope() as session:
                cached = await peer_store.cached_taggings(
                    session, [m.post_id for m in to_tag], TAGGING_PROMPT_VERSION
                )
        except Exception as exc:  # noqa: BLE001 — cache is an optimisation only
            log.debug("tagging cache read skipped: %s", exc)

    fresh = await tag_posts([m for m in to_tag if m.post_id not in cached])
    taggings = [*cached.values(), *fresh]

    # Lift over every post that actually got tagged (winners vs the rest).
    by_id = {m.post_id: m for m in all_metrics}
    attributes = lift_attributes(all_metrics, taggings)
    items = [
        LiftItem(
            attributes=attrs,
            is_winner=post_id in winner_ids,
            outlier_views=by_id[post_id].outlier_views,
        )
        for post_id, attrs in attributes.items()
        if post_id in by_id
    ]
    report = build_report(
        niche=niche,
        accounts=list(baselines.values()),
        selection=selection,
        taggings=taggings,
        lift_rows=build_lift_table(items),
        now=now,
    )

    # Every account failed -> that is a failed run, not "the niche is quiet".
    if not posts_by_handle and failures:
        report = report.model_copy(update={"status": "failed"})

    report_id: int | None = None
    if persist:
        try:
            async with database.session_scope() as session:
                if taggings:
                    await peer_store.save_taggings(session, taggings)
                report_id = await peer_store.save_report(session, profile_id, report)
        except Exception as exc:  # noqa: BLE001 — persistence never fails the tool call
            log.warning("peer pipeline persistence skipped: %s", exc)

    return PipelineResult(
        report=report,
        taggings=taggings,
        metrics=all_metrics,
        scanned=scanned,
        failures=failures,
        report_id=report_id,
    )
