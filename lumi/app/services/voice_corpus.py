"""Chroma-backed voice corpus: index a profile's posts and retrieve diverse extraction samples.

The corpus lives in the `voice_corpus` Chroma collection (see app/services/chroma.py).
Postgres remains the source of truth — this is a derived index used to pick a
diverse, temporally-spread sample of posts for voice extraction instead of the
old `posts[:10]` arbitrary slice. Every helper degrades to a no-op / None when
Chroma is unavailable so extraction falls back to the DB path.
"""

import logging
from typing import TYPE_CHECKING, Any

from app.services.chroma import VOICE_CORPUS, get_collection
from app.services.pfm import is_authentic_original

if TYPE_CHECKING:
    from app.models.post import Post

log = logging.getLogger(__name__)

MAX_CORPUS_DOCS = 200  # safety cap when loading a profile's full corpus


def _corpus_id(profile_id: int, post_pk: int) -> str:
    return f"{profile_id}:{post_pk}"


def upsert_posts(profile_id: int, posts: list["Post"]) -> int:
    """Upsert Post model instances into the voice_corpus collection. Returns count upserted."""
    col = get_collection(VOICE_CORPUS)
    if col is None or not posts:
        return 0

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, Any]] = []
    for p in posts:
        caption = (p.caption or "").strip()
        if p.id is None or not caption:
            continue
        if not is_authentic_original(caption):
            continue
        pub = p.published_at.isoformat() if p.published_at else ""
        ids.append(_corpus_id(profile_id, p.id))
        docs.append(caption)
        metas.append({"profile_id": profile_id, "post_id": p.id, "published_at": pub})

    if not ids:
        return 0
    try:
        col.upsert(ids=ids, documents=docs, metadatas=metas)
        return len(ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("voice_corpus upsert failed for profile %s: %s", profile_id, exc)
        return 0


def clear_profile_corpus(profile_id: int) -> bool:
    """Delete every corpus doc for a profile (used when polluted rows are removed)."""
    col = get_collection(VOICE_CORPUS)
    if col is None:
        return False
    try:
        col.delete(where={"profile_id": profile_id})
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("voice_corpus clear failed for profile %s: %s", profile_id, exc)
        return False


async def sync_profile_corpus(profile_id: int) -> int:
    """Load all posts for a profile from the DB and upsert them into the corpus."""
    from sqlmodel import select

    from app.database import session_scope
    from app.models.post import Post

    async with session_scope() as session:
        posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()
    return upsert_posts(profile_id, posts)


def retrieve_extraction_sample(profile_id: int, limit: int = 10) -> list[dict[str, Any]] | None:
    """Retrieve a temporally-spread, diverse sample for voice extraction.

    Returns a list of {"caption": str, "post_id": int} ordered oldest -> newest,
    or None when the corpus is empty / unavailable (caller should fall back to the
    DB posts path).
    """
    col = get_collection(VOICE_CORPUS)
    if col is None:
        return None
    try:
        res = col.get(where={"profile_id": profile_id}, limit=MAX_CORPUS_DOCS)
        metas = res.get("metadatas") or []
        docs = res.get("documents") or []
        if not docs:
            return None

        # Sort by published_at (oldest first) when available for temporal spread
        paired = list(zip(docs, metas, strict=False))
        paired.sort(key=lambda t: (t[1] or {}).get("published_at") or "")

        rows = [
            {"caption": d, "post_id": (m or {}).get("post_id")}
            for d, m in paired
            if d and d.strip()
        ]
        if not rows:
            return None
        if len(rows) <= limit:
            return rows

        # Spread-sample across the full history: every k-th post
        step = len(rows) / limit
        sampled: list[dict[str, Any]] = []
        seen: set[int] = set()
        i = 0.0
        while len(sampled) < limit and int(i) < len(rows):
            idx = int(i)
            if idx not in seen:
                sampled.append(rows[idx])
                seen.add(idx)
            i += step
        return sampled or None
    except Exception as exc:  # noqa: BLE001
        log.warning("voice_corpus retrieval failed for profile %s: %s", profile_id, exc)
        return None
