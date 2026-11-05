"""Chroma client for agentic storage (voice corpus, peer frameworks, agent memory).

Uses Chroma Cloud when CHROMA_API_KEY is set (prod); otherwise falls back to a
local PersistentClient at CHROMA_PATH (dev). Every public helper degrades to a
no-op when Chroma is unavailable — the app must never hard-depend on it.
"""

import logging
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

VOICE_CORPUS = "voice_corpus"
VOICE_PROFILES = "voice_profiles"
PEER_FRAMEWORKS = "peer_frameworks"
PEER_POSTS = "peer_posts"
AGENT_MEMORY = "agent_memory"

COLLECTIONS = (VOICE_CORPUS, VOICE_PROFILES, PEER_FRAMEWORKS, PEER_POSTS, AGENT_MEMORY)

_client: Any = None
_initialized = False


def get_chroma_client() -> Any:
    """Lazy singleton. Returns the Cloud or Persistent client, or None on failure."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    settings = get_settings()
    try:
        import chromadb

        if settings.chroma_api_key:
            _client = chromadb.CloudClient(
                api_key=settings.chroma_api_key,
                tenant=settings.chroma_tenant,
                database=settings.chroma_database,
            )
            log.info("Chroma Cloud client ready (database=%s)", settings.chroma_database)
        else:
            _client = chromadb.PersistentClient(path=settings.chroma_path)
            log.info("Chroma PersistentClient ready (path=%s)", settings.chroma_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Chroma unavailable, agentic storage disabled: %s", exc)
        _client = None

    return _client


def get_collection(name: str) -> Any:
    """Get (or create) a collection, or None when Chroma is down."""
    client = get_chroma_client()
    if client is None:
        return None
    try:
        return client.get_or_create_collection(name=name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Chroma collection %s unavailable: %s", name, exc)
        return None


def ensure_collections() -> list[str]:
    """Create all known collections at startup. Returns the names created."""
    ready = []
    for name in COLLECTIONS:
        if get_collection(name) is not None:
            ready.append(name)
    return ready


def chroma_available() -> bool:
    return get_chroma_client() is not None
