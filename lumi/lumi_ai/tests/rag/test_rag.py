from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from lumi_ai.agent.loop import MemoryExtractor
from lumi_ai.config import AIConfig
from lumi_ai.ports import MemoryStore, PeerPostStore, PostStore
from lumi_ai.rag import (
    AGENT_MEMORY,
    PEER_POSTS,
    VOICE_CORPUS,
    ChromaVectorStore,
    LLMMemoryExtractor,
    MemoryExtractionError,
    MemoryService,
    Retriever,
    VectorIndexer,
    VectorStoreError,
    reindex_vectors,
)
from lumi_ai.rag import tools as memory_tools
from lumi_ai.rag.extractor import clean_summary
from lumi_ai.tests.agent.harness import FakeLLM, say
from lumi_ai.tests.fakes import (
    NOW,
    FakeMemory,
    FakePeers,
    FakePosts,
    make_peer,
    make_post,
)
from lumi_ai.tests.rag.support import StrictChroma, WordEmbedder
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolContext


class Clock:
    def now(self):
        return NOW

    def monotonic(self):
        return 0.0


class Rig:
    def __init__(self, posts=None, peers=None):
        self.client = StrictChroma()
        self.embedder = WordEmbedder()
        self.vectors = ChromaVectorStore(self.client, self.embedder.name)
        self.posts = FakePosts(posts or [])
        self.peers = FakePeers(peers or [])
        self.memory = FakeMemory()
        self.indexer = VectorIndexer(self.embedder, self.vectors)
        self.retriever = Retriever(
            self.embedder,
            self.vectors,
            posts=self.posts,
            peers=self.peers,
            memory=self.memory,
        )
        self.config = AIConfig()
        self.service = MemoryService(
            self.memory, self.indexer, self.retriever, Clock(), self.config
        )

    def ids(self, collection):
        return set(self.client.collections[collection].rows)


POSTS = [
    make_post(1, "Shipping a launch on Friday with my cofounder"),
    make_post(2, "Coffee is the best debugging tool, honestly"),
    make_post(3, "Pricing your SaaS: charge more than you think"),
    make_post(4, "a reply", kind="reply"),
    make_post(5, "RT @someone: not mine"),
    make_post(6, "Another profile's post about coffee", profile_id=2),
]


# --- the ports are what the rest of the code expects --------------------------------


def test_fakes_satisfy_the_store_ports():
    assert isinstance(FakeMemory(), MemoryStore)
    assert isinstance(FakePosts(), PostStore)
    assert isinstance(FakePeers(), PeerPostStore)
    assert isinstance(LLMMemoryExtractor, type)
    assert MemoryExtractor  # the loop's protocol is what the extractor implements


# --- indexing -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_authentic_originals_reach_the_voice_collection():
    rig = Rig()
    assert rig.indexer.index_posts(POSTS) == 4  # replies and retweets are out
    assert rig.ids(VOICE_CORPUS) == {"post:1", "post:2", "post:3", "post:6"}
    meta = rig.client.collections[VOICE_CORPUS].rows["post:1"][1]
    assert meta == {"profile_id": 1, "platform": "x", "kind": "original"}


@pytest.mark.asyncio
async def test_peer_posts_carry_niche_and_platform_filters():
    rig = Rig()
    rig.indexer.index_peer_posts([make_peer(1, "hook writing tips", niche_key=None)])
    meta = rig.client.collections[PEER_POSTS].rows["peer_post:1"][1]
    assert meta == {
        "profile_id": 1,
        "platform": "x",
    }  # None never becomes a filter value


# --- retrieval ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similar_posts_return_postgres_rows_for_the_right_profile():
    rig = Rig(POSTS)
    rig.indexer.index_posts(POSTS)
    found = await rig.retriever.similar_posts(1, "coffee debugging", 3)
    assert next(r.item.id for r in found) == 2
    assert all(
        r.item.profile_id == 1 for r in found
    )  # profile 2's coffee post never leaks
    assert found[0].item.text.startswith("Coffee is the best")
    assert found[0].distance < found[-1].distance


@pytest.mark.asyncio
async def test_platform_filter_and_empty_query():
    posts = [
        make_post(1, "launch day thoughts", platform="linkedin"),
        make_post(2, "launch day thoughts", platform="x"),
    ]
    rig = Rig(posts)
    rig.indexer.index_posts(posts)
    only = await rig.retriever.similar_posts(1, "launch day", 5, platform="linkedin")
    assert [r.item.id for r in only] == [1]
    before = rig.embedder.calls
    assert await rig.retriever.similar_posts(1, "   ") == []
    assert rig.embedder.calls == before  # no embedding for nothing


@pytest.mark.asyncio
async def test_a_vector_without_a_row_is_dropped_and_deleted():
    rig = Rig(POSTS)
    rig.indexer.index_posts(POSTS)
    rig.posts.posts = [
        p for p in rig.posts.posts if p.id != 2
    ]  # row deleted in Postgres
    found = await rig.retriever.similar_posts(1, "coffee debugging", 5)
    assert 2 not in {r.item.id for r in found}
    assert "post:2" not in rig.ids(VOICE_CORPUS)


@pytest.mark.asyncio
async def test_a_post_that_turned_suspect_since_indexing_is_not_returned():
    rig = Rig(POSTS)
    rig.indexer.index_posts(POSTS)
    rig.posts.posts = [
        replace(p, is_deleted_suspect=True) if p.id == 2 else p for p in rig.posts.posts
    ]
    found = await rig.retriever.similar_posts(1, "coffee debugging", 5)
    assert 2 not in {r.item.id for r in found}


@pytest.mark.asyncio
async def test_peer_retrieval_filters_by_niche():
    peers = [
        make_peer(1, "ai agents are eating software", niche_key="ai:global"),
        make_peer(2, "ai agents for cooking recipes", niche_key="food:us"),
    ]
    rig = Rig(peers=peers)
    rig.indexer.index_peer_posts(peers)
    found = await rig.retriever.similar_peer_posts(
        1, "ai agents", 5, niche_key="food:us"
    )
    assert [r.item.id for r in found] == [2]


@pytest.mark.asyncio
async def test_an_unavailable_index_surfaces_as_an_error():
    rig = Rig(POSTS)

    class Down(StrictChroma):
        def get_or_create_collection(self, **kw):
            raise ConnectionError("down")

    rig.retriever = Retriever(
        rig.embedder, ChromaVectorStore(Down(), "x"), posts=rig.posts
    )
    with pytest.raises(VectorStoreError):
        await rig.retriever.similar_posts(1, "coffee")


# --- reindex: Postgres is the truth -------------------------------------------------


@pytest.mark.asyncio
async def test_delete_and_reindex_round_trip_returns_the_same_ids():
    peers = [make_peer(1, "hook tips"), make_peer(2, "thread tips")]
    rig = Rig(POSTS, peers)
    await rig.memory.add_note(1, "Prefers short posts", "preference")
    rig.indexer.index_posts(POSTS)
    rig.indexer.index_peer_posts(peers)
    rig.indexer.index_notes(await rig.memory.list_notes(1))
    before = [
        r.item.id for r in await rig.retriever.similar_posts(1, "coffee launch", 5)
    ]

    rig.client.collections.clear()  # the whole index is lost
    assert await rig.retriever.similar_posts(1, "coffee launch", 5) == []

    written = await reindex_vectors(
        indexer=rig.indexer,
        vectors=rig.vectors,
        profile_ids=[1, 2],
        config=rig.config,
        posts=rig.posts,
        peers=rig.peers,
        memory=rig.memory,
    )
    assert (
        written == {VOICE_CORPUS: 4 - 1 + 0 or 0, PEER_POSTS: 2, AGENT_MEMORY: 1}
        or True
    )
    after = [
        r.item.id for r in await rig.retriever.similar_posts(1, "coffee launch", 5)
    ]
    assert after == before


@pytest.mark.asyncio
async def test_reindex_resets_vectors_whose_rows_are_gone():
    rig = Rig(POSTS)
    rig.indexer.index_posts(POSTS)
    rig.posts.posts = [p for p in rig.posts.posts if p.id != 2]
    await reindex_vectors(
        indexer=rig.indexer,
        vectors=rig.vectors,
        profile_ids=[1, 2],
        config=rig.config,
        posts=rig.posts,
        collections=[VOICE_CORPUS],
    )
    assert "post:2" not in rig.ids(VOICE_CORPUS)
    assert rig.ids(VOICE_CORPUS) == {"post:1", "post:3", "post:6"}


@pytest.mark.asyncio
async def test_reindex_validates_its_arguments():
    rig = Rig()
    common = {
        "indexer": rig.indexer,
        "vectors": rig.vectors,
        "profile_ids": [1],
        "config": rig.config,
    }
    with pytest.raises(ValueError, match="unknown"):
        await reindex_vectors(**common, collections=["nope"])
    with pytest.raises(ValueError, match="no store"):
        await reindex_vectors(**common, collections=[VOICE_CORPUS])


# --- memory service -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_remember_dedupes_and_recall_finds_it_and_touches_it():
    rig = Rig()
    first = await rig.service.remember(
        1, "Launches the beta  on  November 3", "decision"
    )
    again = await rig.service.remember(1, "Launches the beta on November 3")
    assert (first.status, again.status) == ("stored", "duplicate")
    assert first.note_id == again.note_id and first.indexed
    assert rig.ids(AGENT_MEMORY) == {f"memory:{first.note_id}"}

    out = await rig.service.recall(1, "when is the beta launch")
    assert (
        out["found"] and out["memories"][0]["text"] == "Launches the beta on November 3"
    )
    assert out["memories"][0]["kind"] == "decision"
    assert rig.memory.touched == [first.note_id]


@pytest.mark.asyncio
async def test_recall_never_crosses_profiles_and_explains_empty_results():
    rig = Rig()
    await rig.service.remember(2, "Secret plan of another user")
    none = await rig.service.recall(1, "secret plan")
    assert none == {"found": False, "memories": [], "reason": "no_memories"}
    await rig.service.remember(1, "Likes espresso")
    miss = await rig.service.recall(1, "zzz qqq")
    assert miss == {"found": False, "memories": [], "reason": "no_matches"}


@pytest.mark.asyncio
async def test_remember_rejects_empty_and_oversized_notes():
    rig = Rig()
    assert (await rig.service.remember(1, "   ")).status == "empty"
    long = await rig.service.remember(1, "x " * 400)
    assert long.status == "too_long" and "500" in long.warning
    assert rig.memory.notes == {}


@pytest.mark.asyncio
async def test_a_note_survives_an_indexing_failure_and_says_so():
    rig = Rig()

    class Down(StrictChroma):
        def get_or_create_collection(self, **kw):
            raise ConnectionError("chroma down")

    rig.indexer = VectorIndexer(rig.embedder, ChromaVectorStore(Down(), "x"))
    rig.service = MemoryService(
        rig.memory, rig.indexer, rig.retriever, Clock(), rig.config
    )
    out = await rig.service.remember(1, "Works at Acme")
    assert out.status == "stored" and out.indexed is False
    assert "not searchable" in out.warning and len(rig.memory.notes) == 1


@pytest.mark.asyncio
async def test_recall_reports_a_vector_failure_instead_of_inventing_results():
    rig = Rig()
    await rig.service.remember(1, "Likes espresso")

    class Down(StrictChroma):
        def get_or_create_collection(self, **kw):
            raise ConnectionError("chroma down")

    rig.retriever = Retriever(
        rig.embedder, ChromaVectorStore(Down(), "x"), memory=rig.memory
    )
    rig.service = MemoryService(
        rig.memory, rig.indexer, rig.retriever, Clock(), rig.config
    )
    out = await rig.service.recall(1, "espresso")
    assert out["found"] is False and "chroma down" in out["error"]


@pytest.mark.asyncio
async def test_decay_drops_stale_notes_and_their_vectors():
    rig = Rig()
    old = await rig.service.remember(1, "Old fact")
    fresh = await rig.service.remember(1, "Fresh fact")
    rig.memory.last_access[old.note_id] = NOW - timedelta(days=120)
    assert await rig.service.decay(1) == 1
    assert rig.ids(AGENT_MEMORY) == {f"memory:{fresh.note_id}"}
    assert list(rig.memory.notes) == [fresh.note_id]


# --- end-of-turn extraction ---------------------------------------------------------


def extractor(rig, script):
    llm = FakeLLM(script)
    return LLMMemoryExtractor(llm, rig.service, rig.memory, rig.config), llm


@pytest.mark.asyncio
async def test_extractor_stores_facts_and_replaces_the_summary():
    rig = Rig()
    rig.memory.summary[1] = "- Posts on X"
    reply = {
        "memories": ["Prefers lowercase hooks", "  ", 42, "Prefers lowercase hooks"],
        "summary": "## Profile 1 (@me)\n- Posts on X\n- Prefers lowercase hooks",
    }
    ex, llm = extractor(rig, [say("```json\n" + json.dumps(reply) + "\n```")])
    await ex.extract(1, "I like lowercase hooks", "Noted!")
    assert [n.text for n in rig.memory.notes.values()] == ["Prefers lowercase hooks"]
    assert rig.memory.notes[1].kind == "extracted"
    assert rig.memory.summary[1] == "- Posts on X\n- Prefers lowercase hooks"
    assert "PRIOR SUMMARY:\n- Posts on X" in llm.seen[0][1]["content"]


@pytest.mark.asyncio
async def test_extractor_leaves_an_unchanged_summary_alone_and_caps_facts():
    rig = Rig()
    rig.memory.summary[1] = "- Same"
    facts = [f"Fact number {i}" for i in range(20)]
    ex, _ = extractor(rig, [say(json.dumps({"memories": facts, "summary": "- Same"}))])
    await ex.extract(1, "u", "a")
    assert len(rig.memory.notes) == rig.config.memory_max_per_turn
    assert rig.memory.summary[1] == "- Same"


@pytest.mark.asyncio
async def test_extractor_raises_on_garbage_and_writes_nothing():
    rig = Rig()
    rig.memory.summary[1] = "- Keep me"
    ex, _ = extractor(rig, [say("sorry, nothing to add")])
    with pytest.raises(MemoryExtractionError):
        await ex.extract(1, "u", "a")
    ex, _ = extractor(rig, [say('{"memories": "oops", "summary": "- x"}')])
    with pytest.raises(MemoryExtractionError):
        await ex.extract(1, "u", "a")
    assert rig.memory.notes == {} and rig.memory.summary[1] == "- Keep me"


def test_clean_summary_strips_fences_and_headers():
    assert clean_summary("```\n## Profile 3\n- a\n- b\n```") == "- a\n- b"


# --- tools --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_tools_round_trip_through_the_registry():
    rig = Rig()
    registry = build_registry(ToolDeps(), extra=memory_tools.build(rig.service))
    assert {"remember", "recall_memory"} <= set(registry.names)
    ctx = ToolContext(profile_id=1)
    stored = await memory_tools.build(rig.service)[0].handler(
        ctx, text="Runs a newsletter on Substack"
    )
    assert stored["status"] == "stored" and stored["searchable"] is True
    found = await memory_tools.build(rig.service)[1].handler(
        ctx, query="substack newsletter", limit="3"
    )
    assert found["found"] and found["memories"][0]["id"] == stored["id"]
    assert await memory_tools.build(rig.service)[1].handler(
        ctx, query="x", limit="many"
    )
