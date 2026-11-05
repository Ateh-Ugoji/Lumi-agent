"""Chroma-backed peer-framework corpus: index extracted frameworks + peer winner posts.

Derived index over the `peer_frameworks` / `peer_posts` collections (Postgres stays
the source of truth for `peer_frameworks` rows). Powers the retrieval-first
`get_peer_advice` tool. Every helper degrades to a no-op / empty result when
Chroma is unavailable so callers can fall back to live Xpoz + LLM extraction.
"""

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from app.services.chroma import PEER_FRAMEWORKS, PEER_POSTS, get_collection

if TYPE_CHECKING:
    from app.models.frameworks import PeerFramework

log = logging.getLogger(__name__)

MAX_QUERY_RESULTS = 5


def framework_document(payload: dict[str, Any]) -> str:
    """Render a framework payload as searchable text for embedding."""
    parts: list[str] = []
    if payload.get("niche_title"):
        parts.append(f"Niche: {payload['niche_title']}")
    handles = payload.get("top_peer_handles") or []
    if handles:
        parts.append("Top peers: " + ", ".join(f"@{str(h).lstrip('@')}" for h in handles))
    for p in payload.get("content_pillars") or []:
        parts.append(
            f"Content pillar: {p.get('pillar_name')} ({p.get('percentage_of_posts')}% of posts) — "
            f"{p.get('description')} Why it works: {p.get('why_it_works')}"
        )
    for f in payload.get("winning_frameworks") or []:
        structure = " > ".join(s for s in (f.get("structure") or []) if s)
        parts.append(
            f"Winning framework: {f.get('framework_name')} — structure: {structure}; "
            f"hook: {f.get('hook_formula')}; engagement driver: {f.get('engagement_driver')}"
        )
    for k, v in (payload.get("pacing_and_format_rules") or {}).items():
        parts.append(f"Pacing/format rule — {k}: {v}")
    for prompt in payload.get("actionable_post_prompts") or []:
        parts.append(f"Actionable post prompt: {prompt}")
    return "\n".join(p for p in parts if p)


def upsert_framework(profile_id: int, row: "PeerFramework") -> bool:
    """Index one persisted PeerFramework row into the peer_frameworks collection."""
    col = get_collection(PEER_FRAMEWORKS)
    if col is None or row.id is None:
        return False
    doc = framework_document(row.payload or {})
    if not doc.strip():
        return False
    try:
        col.upsert(
            ids=[f"{profile_id}:{row.id}"],
            documents=[doc],
            metadatas=[
                {
                    "profile_id": profile_id,
                    "framework_id": row.id,
                    "query": row.query or "",
                    "niche_title": row.niche_title or "",
                }
            ],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("framework upsert failed for profile %s: %s", profile_id, exc)
        return False


def upsert_peer_posts(profile_id: int, query: str, posts: list[dict[str, Any]]) -> int:
    """Index raw Xpoz winner posts into the peer_posts collection. Returns count upserted."""
    col = get_collection(PEER_POSTS)
    if col is None or not posts:
        return 0

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, Any]] = []
    for p in posts:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        ref = str(p.get("id") or "").strip()
        if not ref:
            ref = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
        author = str(p.get("authorUsername") or "").lstrip("@")
        impressions = int(p.get("impressionCount") or 0)
        ids.append(f"{profile_id}:{ref}")
        docs.append(text)
        metas.append(
            {
                "profile_id": profile_id,
                "query": query,
                "author": author,
                "impressions": impressions,
            }
        )

    if not ids:
        return 0
    try:
        col.upsert(ids=ids, documents=docs, metadatas=metas)
        return len(ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("peer_posts upsert failed for profile %s: %s", profile_id, exc)
        return 0


def _query_collection(name: str, profile_id: int, query: str, n: int) -> list[dict[str, Any]]:
    col = get_collection(name)
    if col is None:
        return []
    try:
        # Skip querying an empty index (Chroma errors on n_results > element count)
        existing = col.get(where={"profile_id": profile_id}, limit=1)
        if not existing.get("ids"):
            return []
        res = col.query(query_texts=[query], n_results=n, where={"profile_id": profile_id})
    except Exception as exc:  # noqa: BLE001
        log.warning("corpus query failed (%s, profile %s): %s", name, profile_id, exc)
        return []

    out: list[dict[str, Any]] = []
    for batch_idx in range(len(res.get("ids") or [])):
        for i, doc_id in enumerate(res["ids"][batch_idx]):
            meta = (res.get("metadatas") or [[]])[batch_idx][i]
            distance = (res.get("distances") or [[]])[batch_idx][i]
            out.append(
                {
                    "id": doc_id,
                    "text": (res.get("documents") or [[]])[batch_idx][i],
                    "metadata": meta or {},
                    "distance": distance,
                }
            )
    return out


def query_frameworks(profile_id: int, query: str, n: int = 3) -> list[dict[str, Any]]:
    """Semantic search over stored frameworks for this profile."""
    return _query_collection(PEER_FRAMEWORKS, profile_id, query, min(n, MAX_QUERY_RESULTS))


def query_peer_posts(profile_id: int, query: str, n: int = 5) -> list[dict[str, Any]]:
    """Semantic search over stored peer-winner posts for this profile."""
    return _query_collection(PEER_POSTS, profile_id, query, min(n, MAX_QUERY_RESULTS))


async def sync_frameworks_from_db() -> int:
    """Startup backfill: index every persisted PeerFramework row into Chroma."""
    from sqlmodel import select

    from app.database import session_scope
    from app.models.frameworks import PeerFramework

    async with session_scope() as session:
        rows = (await session.exec(select(PeerFramework))).all()
    indexed = 0
    for row in rows:
        if row.profile_id is not None and upsert_framework(row.profile_id, row):
            indexed += 1
    return indexed
