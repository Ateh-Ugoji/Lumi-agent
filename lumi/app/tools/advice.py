"""Retrieval-first peer advice tool.

Searches the Chroma store (peer_frameworks + peer_posts) first for instant answers.
Only falls back to a live Xpoz search + LLM extraction when the store is empty,
and persists whatever the live path finds so the next call is fast.
Retrieved candidates pass through a Jev relevance filter (keeps >= 0.6) so the
agent only sees advice that actually matches the request; if Jev is unavailable
the unfiltered candidates are returned.
"""

import logging
import time
from datetime import UTC, datetime

from app.services import jev
from app.services.framework_corpus import query_frameworks, query_peer_posts
from app.tools.registry import tool

log = logging.getLogger(__name__)

RELEVANCE_THRESHOLD = 0.6
RELEVANCE_FILTER_CAP = 4


async def _store_provenance(framework_items: list[dict], post_items: list[dict]) -> dict:
    """Rule-18 provenance for stored frameworks: which niche, which accounts, how old.

    Without this the agent presents the default AI-builder frameworks as if they
    were results about whatever account the user named (the Beacons failure).
    Best-effort: a DB/Chroma miss degrades to unknown fields, never raises.
    """
    niche_titles: set[str] = set()
    handles: set[str] = set()
    fw_ids: list[int] = []

    for item in framework_items:
        meta = item.get("metadata") or {}
        title = str(meta.get("niche_title") or "").strip()
        if title:
            niche_titles.add(title)
        fid = meta.get("framework_id")
        if fid is not None:
            try:
                fw_ids.append(int(fid))
            except (TypeError, ValueError):
                continue

    for item in post_items:
        author = str((item.get("metadata") or {}).get("author") or "").lstrip("@").lower()
        if author:
            handles.add(author)

    oldest: datetime | None = None
    if fw_ids:
        try:
            from sqlmodel import select

            from app.database import session_scope
            from app.models.frameworks import PeerFramework

            async with session_scope() as session:
                rows = (
                    await session.exec(
                        select(PeerFramework).where(PeerFramework.id.in_(fw_ids))
                    )
                ).all()
            for row in rows:
                if row.niche_title:
                    niche_titles.add(row.niche_title)
                for h in (row.payload or {}).get("top_peer_handles") or []:
                    normalized = str(h).lstrip("@").lower()
                    if normalized:
                        handles.add(normalized)
                if row.created_at is not None and (oldest is None or row.created_at < oldest):
                    oldest = row.created_at
        except Exception as exc:  # noqa: BLE001 - provenance is best-effort
            log.warning("provenance lookup failed: %s", exc)

    age_days: int | None = None
    if oldest is not None:
        age_days = max(0, (datetime.now(UTC) - oldest).days)

    return {
        "niche_title": ", ".join(sorted(niche_titles)) or None,
        "source_handles": sorted(handles),
        "age_days": age_days,
    }


async def _relevance_filter(
    query: str, frameworks: list[dict], posts: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Keep only candidates Jev scores >= RELEVANCE_THRESHOLD for this query.

    Caps both lists at RELEVANCE_FILTER_CAP, batches every candidate into one
    Jev round trip, and fails open (returns input unchanged) when Jev is down.
    """
    fw = frameworks[:RELEVANCE_FILTER_CAP]
    pe = posts[:RELEVANCE_FILTER_CAP]
    if not fw and not pe:
        return frameworks, posts

    questions: dict[str, str] = {}
    for i, f in enumerate(fw):
        questions[f"framework_{i}"] = (
            "How relevant is this stored content framework to the advice request? "
            f"Framework: {str(f.get('text'))[:600]}"
        )
    for i, p in enumerate(pe):
        questions[f"post_{i}"] = (
            "How relevant is this peer post to the advice request? "
            f"Post: {str(p.get('text'))[:600]}"
        )

    started = time.monotonic()
    scores = await jev.ask_noul(state={"advice_request": query}, questions=questions)
    log.info(
        "advice relevance filter: %d candidates in %.0fms (jev=%s)",
        len(questions), (time.monotonic() - started) * 1000, "ok" if scores else "down",
    )
    if scores is None:
        return fw, pe

    def keep(prefix: str, items: list[dict]) -> list[dict]:
        kept = []
        for i, item in enumerate(items):
            score = scores.get(f"{prefix}_{i}")
            # Fail open on a missing score; only drop on an explicit low score.
            if score is None or float(score) >= RELEVANCE_THRESHOLD:
                kept.append(item)
        return kept

    return keep("framework", fw), keep("post", pe)


@tool(
    name="get_peer_advice",
    description=(
        "Retrieval-first peer advice: searches this profile's stored niche frameworks and peer-winner posts "
        "and returns matching results instantly. Use for questions about what works in the user's niche, "
        "content pillars, post structures, hooks, or peer strategies. Falls back to a live niche scan "
        "(Xpoz + LLM) only when nothing is stored yet, and stores what it finds."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "query": {
                "type": "string",
                "description": "What the user wants advice on (e.g. 'launch hooks', 'building in public pacing')",
            },
        },
        "required": ["profile_id", "query"],
    },
    cost="credits",
    side_effects="writes_db",
)
async def get_peer_advice(profile_id: int, query: str) -> dict:
    frameworks = query_frameworks(profile_id, query)
    posts = query_peer_posts(profile_id, query)
    frameworks, posts = await _relevance_filter(query, frameworks, posts)

    if frameworks or posts:
        return {
            "profile_id": profile_id,
            "query": query,
            "source": "store",
            "found": True,
            "frameworks": frameworks,
            "peer_posts": posts,
            # Rule 18: the model may only use these as evidence about an account
            # that appears in source_handles; otherwise it must say they're from
            # a different niche (see prompt rules 15/18).
            **await _store_provenance(frameworks, posts),
        }

    # Store empty → one live extraction, which persists + indexes for next time
    from app.tools.listening import discover_and_extract_niche_frameworks

    try:
        live = await discover_and_extract_niche_frameworks(profile_id, query=query)
    except Exception as exc:  # noqa: BLE001
        log.warning("live framework extraction failed for profile %s: %s", profile_id, exc)
        return {
            "profile_id": profile_id,
            "query": query,
            "source": "none",
            "found": False,
            "reason": f"no stored frameworks and live extraction failed: {exc}",
        }

    frameworks = query_frameworks(profile_id, query)
    posts = query_peer_posts(profile_id, query)
    frameworks, posts = await _relevance_filter(query, frameworks, posts)
    found = bool(frameworks or posts)
    result = {
        "profile_id": profile_id,
        "query": query,
        "source": "live_extraction",
        "found": found,
        "frameworks": frameworks,
        "peer_posts": posts,
        "qualifying_posts_count": live.get("qualifying_posts_count"),
    }
    if found:
        result.update(await _store_provenance(frameworks, posts))
    if not found:
        result["reason"] = "no stored frameworks and live extraction found no qualifying peer posts"
    return result
