import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlmodel import select

from app.database import session_scope
from app.models.poll import PollConfig
from app.models.post import MetricSnapshot, Post
from app.services import handle_db, jev
from app.services.metrics import detect_spike
from app.tools.registry import tool

DEFAULT_INTERVAL_MINUTES = 5

# Jev spike backstop: velocity detection needs >=2 snapshots, which the poller
# never produces. For never-alerted posts with meaningful absolute engagement
# (>=50 likes), ask Jev whether the post is "notable" instead. Capped per call.
SPIKE_JEV_LIKE_FLOOR = 50
SPIKE_JEV_MAX_JUDGMENTS = 3

logger = logging.getLogger(__name__)

# Xpoz upstream failures are transient more often than they are fatal (the
# post-search endpoint has flapped between 401s and 500s), so one retry buys
# back most failed turns. Non-transient errors are never retried: repeating a
# 401/402/403 only burns time and credits.
XPOZ_ATTEMPTS = 2
XPOZ_RETRY_BACKOFF_SECONDS = 1.5


def _is_transient_xpoz_error(exc: Exception) -> bool:
    """5xx and transport failures heal on retry; 4xx (bad key, credits) never do."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.RequestError)


async def _with_xpoz_retry(operation):
    """Run one Xpoz call, retrying once on a transient upstream failure.

    Raises the last error for the caller to report. This helper never invents
    a result: a failed search stays a failed search, reported honestly.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except Exception as exc:
            if attempt >= XPOZ_ATTEMPTS or not _is_transient_xpoz_error(exc):
                raise
            logger.warning(
                "Xpoz call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                XPOZ_ATTEMPTS,
                XPOZ_RETRY_BACKOFF_SECONDS,
                exc,
            )
            await asyncio.sleep(XPOZ_RETRY_BACKOFF_SECONDS)


def _xpoz_unavailable_message(exc: Exception) -> str:
    """User-facing wording for a search that produced nothing."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 402, 403):
            return (
                f"Xpoz rejected the request (HTTP {status}): the API key is invalid "
                "or out of credits, so no posts could be read. Nothing was analyzed."
            )
        return (
            f"Xpoz post search failed upstream (HTTP {status}). "
            "Nothing was analyzed — try again in a moment."
        )
    return (
        f"Xpoz post search could not reach the upstream service ({type(exc).__name__}). "
        "Nothing was analyzed — try again in a moment."
    )


@tool(
    name="start_listening",
    description="Start polling a profile's recent posts for engagement spikes ('trending' posts).",
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "interval_minutes": {"type": "integer"},
        },
        "required": ["profile_id"],
    },
    side_effects="writes_db",
)
async def start_listening(profile_id: int, interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> dict:
    async with session_scope() as session:
        config = (await session.exec(select(PollConfig).where(PollConfig.profile_id == profile_id))).first()
        if config is None:
            config = PollConfig(profile_id=profile_id)

        config.is_active = True
        config.interval_minutes = interval_minutes
        session.add(config)
        await session.commit()

    return {"profile_id": profile_id, "listening": True, "interval_minutes": interval_minutes}


@tool(
    name="stop_listening",
    description="Stop polling a profile for trending posts.",
    parameters={"type": "object", "properties": {"profile_id": {"type": "integer"}}, "required": ["profile_id"]},
    side_effects="writes_db",
)
async def stop_listening(profile_id: int) -> dict:
    async with session_scope() as session:
        config = (await session.exec(select(PollConfig).where(PollConfig.profile_id == profile_id))).first()
        if config is None:
            return {"profile_id": profile_id, "listening": False}

        config.is_active = False
        session.add(config)
        await session.commit()

    return {"profile_id": profile_id, "listening": False}


@tool(
    name="check_trending",
    description="Check a profile's tracked posts for engagement spikes and mark any newly trending ones as alerted.",
    parameters={"type": "object", "properties": {"profile_id": {"type": "integer"}}, "required": ["profile_id"]},
    cost="llm",
    side_effects="writes_db",
)
async def check_trending(profile_id: int) -> dict:
    newly_alerted_post_ids: list[int] = []
    jev_judgments = 0

    async with session_scope() as session:
        posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()

        for post in posts:
            snapshots = (
                await session.exec(select(MetricSnapshot).where(MetricSnapshot.post_id == post.id))
            ).all()

            spiked = detect_spike(list(snapshots))
            already_alerted = post.alerted_at is not None and not post.alert_dismissed

            if spiked:
                if already_alerted:
                    continue  # already alerted and not yet acted on
            else:
                # Jev backstop for the dead velocity path
                if already_alerted or not snapshots:
                    continue
                latest = max(snapshots, key=lambda s: s.captured_at)
                if latest.likes < SPIKE_JEV_LIKE_FLOOR:
                    continue
                if jev_judgments >= SPIKE_JEV_MAX_JUDGMENTS:
                    continue
                jev_judgments += 1
                verdict = await jev.ask_choice(
                    state={
                        "caption": (post.caption or "")[:500],
                        "likes": latest.likes,
                        "comments": latest.comments,
                        "shares": latest.shares,
                        "views": latest.views,
                    },
                    name="engagement",
                    instructions=(
                        "Is this post's absolute engagement notable enough to alert the creator?"
                    ),
                    criteria={
                        "notable": (
                            "Engagement is clearly exceptional for an ordinary post "
                            "(hundreds to thousands of likes, or unusually high comments/shares)."
                        ),
                        "ordinary": (
                            "Engagement is within a normal range and does not warrant an alert."
                        ),
                    },
                )
                if verdict != "notable":
                    continue
                logger.info("jev spike backstop: alerting post %s (%d likes)", post.id, latest.likes)

            post.alerted_at = datetime.now(UTC)
            post.alert_dismissed = False
            session.add(post)
            await session.commit()
            newly_alerted_post_ids.append(post.id)

        config = (await session.exec(select(PollConfig).where(PollConfig.profile_id == profile_id))).first()
        if config is not None:
            config.last_polled_at = datetime.now(UTC)
            session.add(config)
            await session.commit()

    return {
        "profile_id": profile_id,
        "newly_alerted_post_ids": newly_alerted_post_ids,
        "jev_judgments": jev_judgments,
    }


@tool(
    name="check_niche_trends",
    description=(
        "Fetch trending tweets from specified public accounts in the user's niche using Xpoz. "
        "Surfaces viral candidate tweets with high engagement that can be repurposed in the user's voice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "handles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of public X usernames to monitor (e.g. ['sama', 'levelsio'])",
            },
            "min_likes": {
                "type": "integer",
                "description": "Minimum likes threshold to consider a tweet viral (default: 50)",
            },
        },
        "required": ["profile_id", "handles"],
    },
    cost="credits",
    side_effects="writes_db",
)
async def check_niche_trends(
    profile_id: int,
    handles: list[str],
    min_likes: int = 50,
) -> dict:
    from app.models.listening import ListeningMatch
    from app.services.xpoz import XpozClient

    # Registry dispatch does no type coercion: the model can pass min_likes as
    # a JSON string ("50"), and `like_count < min_likes` then raises TypeError
    # (observed live 2026-10-21, tool died before any post was checked).
    # Coerce defensively; unparseable -> schema default.
    try:
        min_likes = int(min_likes)
    except (TypeError, ValueError):
        min_likes = 50

    client = XpozClient()
    saved_matches = []
    authors: dict[str, str] = {}  # every author the search surfaced (lower -> as-is)
    failures: list[str] = []
    scanned: dict[str, int] = {}  # handle (lower) -> posts fetched for it

    try:
        async with session_scope() as session:
            for handle in handles:
                try:
                    results = await _with_xpoz_retry(
                        lambda username=handle: client.get_user_live_posts(
                            username=username, limit=10
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to fetch Xpoz posts for @%s: %s", handle, exc)
                    failures.append(f"@{handle}: {exc}")
                    continue
                scanned[str(handle).lstrip("@").lower()] = len(results)

                for tweet in results:

                    post_id = str(tweet.get("id") or "")
                    text = (tweet.get("text") or "").strip()
                    like_count = int(tweet.get("likeCount") or 0)
                    retweet_count = int(tweet.get("retweetCount") or 0)

                    # Every user this search surfaced feeds the shared handle DB —
                    # captured before the threshold so non-viral authors aren't lost.
                    author_name = str(tweet.get("authorUsername") or "").strip().lstrip("@")
                    if author_name:
                        authors[author_name.lower()] = author_name

                    # Only capture viral posts matching the threshold
                    if like_count < min_likes or not post_id or not text:
                        continue

                    author = tweet.get("authorUsername") or handle.lstrip("@")
                    platform_url = f"https://x.com/{author}/status/{post_id}"

                    existing = (
                        await session.exec(
                            select(ListeningMatch).where(
                                ListeningMatch.profile_id == profile_id,
                                ListeningMatch.platform_post_id == post_id,
                            )
                        )
                    ).first()

                    if existing is None:
                        match = ListeningMatch(
                            profile_id=profile_id,
                            platform="x",
                            platform_post_id=post_id,
                            author_handle=author,
                            caption=text,
                            platform_url=platform_url,
                            metrics={
                                "like_count": like_count,
                                "retweet_count": retweet_count,
                                "reply_count": tweet.get("replyCount") or 0,
                                "impression_count": tweet.get("impressionCount") or 0,
                            },
                        )
                        session.add(match)
                        saved_matches.append({
                            "author": author,
                            "caption": text,
                            "likes": like_count,
                            "retweets": retweet_count,
                            "url": platform_url,
                        })

            await session.commit()
    finally:
        await client.aclose()

    # The handle DB grows with every search: the tracked accounts (bounded
    # enrichment — picture/name/followers for handles never seen before) plus
    # every author the search surfaced. Best-effort: the DB is a help layered
    # on, never a dependency of the scan itself.
    try:
        await handle_db.remember_scanned(handles, origin="niche")
        handle_db.remember([{"handle": a} for a in authors.values()], origin="niche")
    except Exception as exc:  # noqa: BLE001 — never fail a scan over the handle DB
        logger.debug("handle_db save skipped: %s", exc)

    result = {
        "profile_id": profile_id,
        "new_matches_found": len(saved_matches),
        "viral_posts": saved_matches,
        # Which handles this call actually got posts for (handle -> fetched count).
        # The loop's coverage gate (prompt rule 17) reads this to tell
        # "scanned" from "not run"; the agent uses it for the coverage line.
        "scanned_handles": {
            str(h).lstrip("@").lower(): n for h, n in scanned.items()
        },
    }
    if failures:
        # Partial failures are named so the agent can say which handle missed;
        # a scan where *every* handle failed read nothing at all, so it says so
        # instead of reporting "0 viral posts" as if the niche were quiet.
        result["failed_handles"] = failures
        if not scanned:
            result["error"] = (
                f"Xpoz lookups failed for all {len(failures)} requested handle(s) "
                f"(first: {failures[0]}). No trends were retrieved — try again in a moment."
            )
    return result


@tool(
    name="discover_and_extract_niche_frameworks",
    description=(
        "Automatically discovers high-impression peers and founders in the creator's regional/domain niche, "
        "and extracts the structural frameworks and content pillars driving their traction."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "query": {
                "type": "string",
                "description": "Niche discovery query (e.g. 'founder nigeria startup', 'lagos tech builder')",
            },
        },
        "required": ["profile_id", "query"],
    },
    cost="credits",
    side_effects="writes_db",
)
async def discover_and_extract_niche_frameworks(profile_id: int, query: str) -> dict:
    """Discover niche peers by keyword search, then run the peer pipeline on them.

    Prompt 3 wiring: the search only *discovers* which accounts to read (and
    feeds the shared handle DB); every framework claim comes from
    `run_peer_pipeline` — baseline-relative winners, blind tagging, lift-grounded
    synthesis. There is no canned fallback any more: a run that found nothing
    reports `insufficient_data`/`failed` with empty frameworks, never invented ones.
    """
    from app.database import session_scope
    from app.models.frameworks import PeerFramework
    from app.services.peer_pipeline import (
        legacy_payload_from_report,
        run_peer_pipeline,
        winner_post_dicts,
    )
    from app.services.xpoz import XpozClient

    client = XpozClient()
    try:
        try:
            raw_results = await _with_xpoz_retry(
                lambda: client.search_live_posts(query=query, limit=25)
            )
        except Exception as exc:  # noqa: BLE001 — reported to the agent, never faked
            logger.warning("niche framework search failed (query=%r): %s", query, exc)
            return {
                "profile_id": profile_id,
                "query_used": query,
                "error": _xpoz_unavailable_message(exc),
                "qualifying_posts_count": 0,
                "framework_insights": {},
                "peer_framework_id": None,
            }

        # Every author this keyword search surfaced feeds the shared handle DB
        # (handle-only — a keyword search can surface dozens of authors, so paid
        # picture enrichment stays bounded to scanned/tracked accounts; the bar
        # falls back to unavatar for their picture anyway). Saved even if the
        # LLM step below fails: the search happened, the users were seen.
        try:
            authors = {
                a
                for a in (
                    str(p.get("authorUsername") or "").strip().lstrip("@")
                    for p in raw_results
                )
                if a
            }
            handle_db.remember(
                [{"handle": a} for a in authors], origin="niche", query=query
            )
        except Exception as exc:  # noqa: BLE001 — never fail a search over the handle DB
            logger.debug("handle_db save skipped: %s", exc)

        # Discovery only: the search picks WHICH accounts the analysis reads;
        # the pipeline then fetches each account's own recent posts, so every
        # baseline — and therefore the winner bar — is that account's own numbers.
        handles: list[str] = []
        seen: set[str] = set()
        for post in raw_results:
            author = str(post.get("authorUsername") or "").strip().lstrip("@")
            if author and author.lower() not in seen:
                seen.add(author.lower())
                handles.append(author)

        run = await run_peer_pipeline(
            profile_id=profile_id, niche=query, handles=handles, client=client
        )
        framework_data = legacy_payload_from_report(run.report, query)
        framework_data["report_id"] = run.report_id

        async with session_scope() as session:
            row = PeerFramework(
                profile_id=profile_id,
                query=query,
                niche_title=framework_data.get("niche_title", ""),
                payload=framework_data,
                analyzed_peers_count=framework_data.get("analyzed_peers_count", 0),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

        # Index into Chroma so get_peer_advice can serve it next time (non-fatal)
        from app.services.framework_corpus import upsert_framework, upsert_peer_posts

        upsert_framework(profile_id, row)
        upsert_peer_posts(profile_id, query, winner_post_dicts(run))

        result = {
            "profile_id": profile_id,
            "query_used": query,
            # "qualifying" is baseline-relative now: winners against each
            # account's own 4-week median, not an absolute impression filter.
            "qualifying_posts_count": len(run.report.winner_post_ids),
            "framework_insights": framework_data,
            "peer_framework_id": row.id,
            "report_status": run.report.status,
            "report_id": run.report_id,
            "scanned_handles": run.scanned,
        }
        if run.failures:
            # A partial fetch is a footnote; the report states its own limits.
            result["fetch_failures"] = run.failures
        return result
    finally:
        await client.aclose()


