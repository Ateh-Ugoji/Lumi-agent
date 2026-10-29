"""``reindex_vectors``: Chroma can always be rebuilt from Postgres, with the same ids."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from asgiref.sync import async_to_sync
from django.core.management import call_command

from apps.intelligence.reindex import run_reindex
from apps.intelligence.repos import MemoryRepo, PeerPostRepo, ProfileRepo
from lumi_ai.config import AIConfig
from lumi_ai.ports import NicheIn, PeerPostIn, PostMetrics
from lumi_ai.rag import ChromaVectorStore
from lumi_ai.rag.collections import AGENT_MEMORY, PEER_POSTS
from lumi_ai.tests.rag.support import StrictChroma, WordEmbedder

pytestmark = pytest.mark.django_db


def call(fn, *args, **kwargs):
    return async_to_sync(fn)(*args, **kwargs)


def _seed(profile):
    posts = [
        PeerPostIn(
            platform="x",
            external_id=f"p{i}",
            author_handle="rival",
            text=f"competitor post number {i}",
            published_at=datetime(2026, 10, 1, tzinfo=UTC),
            metrics=PostMetrics(likes=i),
        )
        for i in range(3)
    ]
    call(
        ProfileRepo().save_niche,
        profile.pk,
        NicheIn("ai:global", "AI", tracked_handles={"x": ("rival",)}),
    )
    saved = call(PeerPostRepo().save_peer_posts, profile.pk, posts)
    note, _ = call(MemoryRepo().add_note, profile.pk, "prefers short hooks")
    return saved, note


def _rig():
    chroma = StrictChroma()
    return chroma, ChromaVectorStore(chroma, WordEmbedder.name)


def test_reindex_writes_every_row_with_the_ids_the_indexer_uses(profile):
    saved, note = _seed(profile)
    chroma, vectors = _rig()
    written = call(run_reindex, AIConfig(), embedder=WordEmbedder(), vectors=vectors)
    assert written[PEER_POSTS] == 3 and written[AGENT_MEMORY] == 1
    assert set(chroma.collections[PEER_POSTS].rows) == {
        f"peer_post:{p.id}" for p in saved
    }
    assert set(chroma.collections[AGENT_MEMORY].rows) == {f"memory:{note.id}"}


def test_dropping_the_collection_and_reindexing_restores_the_same_ids(profile):
    _seed(profile)
    chroma, vectors = _rig()
    call(run_reindex, AIConfig(), embedder=WordEmbedder(), vectors=vectors)
    before = set(chroma.collections[PEER_POSTS].rows)
    vectors.reset(PEER_POSTS)
    assert not chroma.collections[PEER_POSTS].rows
    call(
        run_reindex,
        AIConfig(),
        embedder=WordEmbedder(),
        vectors=vectors,
        collections=[PEER_POSTS],
    )
    assert set(chroma.collections[PEER_POSTS].rows) == before


def test_reset_clears_vectors_of_rows_deleted_in_postgres(profile):
    _seed(profile)
    chroma, vectors = _rig()
    call(run_reindex, AIConfig(), embedder=WordEmbedder(), vectors=vectors)
    chroma.collections[PEER_POSTS].rows["peer_post:999999"] = ([0.0], {})
    call(run_reindex, AIConfig(), embedder=WordEmbedder(), vectors=vectors)
    assert "peer_post:999999" not in chroma.collections[PEER_POSTS].rows


def test_the_command_is_registered_and_rejects_an_unknown_collection():
    from django.core.management import CommandError

    with pytest.raises(CommandError):
        call_command("reindex_vectors", "--collection", "nope")
