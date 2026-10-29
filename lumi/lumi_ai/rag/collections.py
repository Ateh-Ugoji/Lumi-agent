"""Collection names, vector id format and the metadata Chroma may hold.

A vector id is ``<type>:<postgres id>``. The text lives in Postgres; Chroma never sees it.
"""

from __future__ import annotations

from typing import Final

VOICE_CORPUS: Final = (
    "voice_corpus"  # ``post:<posts.id>``: the user's own authentic originals
)
PEER_POSTS: Final = (
    "peer_posts"  # ``peer_post:<id>``: competitor posts seen by the analysis
)
AGENT_MEMORY: Final = "agent_memory"  # ``memory:<memory_notes.id>``

COLLECTIONS: Final = (VOICE_CORPUS, PEER_POSTS, AGENT_MEMORY)

TYPE_BY_COLLECTION: Final = {
    VOICE_CORPUS: "post",
    PEER_POSTS: "peer_post",
    AGENT_MEMORY: "memory",
}

#: The only metadata keys a vector may carry: filters, never content.
ALLOWED_METADATA: Final = frozenset({"profile_id", "platform", "kind", "niche_key"})


def vector_id(kind: str, pk: int) -> str:
    return f"{kind}:{int(pk)}"


def parse_vector_id(raw: str) -> tuple[str, int]:
    """Split ``post:42`` into ``("post", 42)``. Raises ``ValueError`` on anything else."""
    kind, sep, tail = raw.partition(":")
    if not sep or not kind or not tail.isdecimal():
        raise ValueError(f"not a vector id: {raw!r}")
    return kind, int(tail)
