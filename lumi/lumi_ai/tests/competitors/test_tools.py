"""Competitor tools through the real registry, against fake ports."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lumi_ai.competitors.pipeline import PipelineDeps
from lumi_ai.competitors.tools import CompetitorServices, build
from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    BudgetExceeded,
    NicheOut,
    PostMetrics,
    PostOut,
    ProfileInfo,
    ProviderAuthError,
)
from lumi_ai.rag.indexer import VectorIndexer
from lumi_ai.rag.retrieval import Retriever
from lumi_ai.rag.vector_store import ChromaVectorStore
from lumi_ai.tests.competitors.support import (
    NOW,
    FakePeerStore,
    FakeReports,
    FakeSocial,
    TaggerLLM,
    make_posts,
)
from lumi_ai.tests.rag.support import StrictChroma, WordEmbedder
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolContext

HANDLES = ["alice", "bob", "carol"]
CTX = ToolContext(profile_id=1, config=AIConfig())


class Profiles:
    def __init__(self, tracked=None):
        self.tracked = tracked or {}

    async def get_profile(self, profile_id):
        return ProfileInfo(profile_id, "Me", "Me_Handle", "x", ("x",))

    async def get_niche(self, profile_id):
        return NicheOut(profile_id, "ai:global", "AI", (), self.tracked, "user", NOW)

    async def save_niche(self, profile_id, niche):
        raise NotImplementedError


class Matches:
    def __init__(self):
        self.rows: set[tuple[int, int]] = set()

    async def record_listening_match(self, profile_id, post_id, score=None):
        key = (profile_id, post_id)
        fresh = key not in self.rows
        self.rows.add(key)
        return fresh


class Own:
    def __init__(self, posts):
        self.posts = posts

    async def list_posts(self, profile_id, *, platform=None, **kw):
        return self.posts


def _services(
    posts=None, errors=None, *, tracked=None, own=None, with_rag=False, llm=None
):
    reports = FakeReports()
    peers = FakePeerStore(reports)
    social = FakeSocial(
        posts if posts is not None else {h: make_posts(h, winners=5) for h in HANDLES},
        errors,
    )
    llm = llm or TaggerLLM(pas_ids=[f"{h}-{i}" for h in HANDLES for i in range(10)])
    pipeline = PipelineDeps(social=social, llm=llm, reports=reports, peer_posts=peers)
    embedder = WordEmbedder()
    retriever = None
    if with_rag:
        vectors = ChromaVectorStore(StrictChroma(), embedder.name)
        indexer = VectorIndexer(embedder, vectors)
        pipeline = PipelineDeps(
            social=social,
            llm=llm,
            reports=reports,
            peer_posts=peers,
            index_peer_posts=indexer.index_peer_posts,
        )
        retriever = Retriever(embedder, vectors, peers=peers)
    services = CompetitorServices(
        pipeline=pipeline,
        profiles=Profiles(tracked),
        posts=Own(own) if own is not None else None,
        matches=Matches(),
        embedder=embedder,
        retriever=retriever,
    )
    registry = build_registry(ToolDeps(), extra=build(services))
    return registry, services, social, reports, peers, llm


async def _call(registry, name, **args):
    return await registry.call(
        CTX, name, {"reason": "the user asked for this analysis", **args}
    )


async def test_discovery_searches_ranks_authors_and_skips_the_own_handle() -> None:
    found = make_posts("alice", 3) + make_posts("bob", 2) + make_posts("me_handle", 9)
    posts = {h: make_posts(h, winners=5) for h in HANDLES}
    posts["search"] = found
    registry, _, social, reports, _, _ = _services(posts)
    out = await _call(
        registry, "discover_and_extract_niche_frameworks", query="AI tools"
    )
    assert out["handles"] == ["alice", "bob"] and out["handles_from_search"]
    assert out["niche_key"] == "ai-tools:global"
    assert out["status"] == reports.reports[0].status
    assert social.calls[0][:3] == ("search", "x", "AI tools")


async def test_discovery_with_given_handles_does_not_search() -> None:
    registry, _, social, _, _, _ = _services()
    out = await _call(
        registry,
        "discover_and_extract_niche_frameworks",
        query="ai tools",
        handles=["@Alice", "BOB", "alice"],
    )
    assert out["handles"] == ["alice", "bob"] and not out["handles_from_search"]
    assert all(c[0] != "search" for c in social.calls)
    assert out["status"] == "ok"
    assert {f["key"] for f in out["frameworks"]} == {"pas"}


async def test_discovery_reports_a_refusing_provider_and_an_empty_search() -> None:
    registry, *_ = _services({"search": []})
    out = await _call(registry, "discover_and_extract_niche_frameworks", query="ai")
    assert "no accounts" in out["error"]
    registry, *_ = _services({}, {"search": ProviderAuthError("bad key")})
    out = await _call(registry, "discover_and_extract_niche_frameworks", query="ai")
    assert "ProviderAuthError" in out["error"]


async def test_discovery_rejects_a_query_without_letters_and_an_unknown_platform() -> (
    None
):
    registry, *_ = _services()
    out = await _call(registry, "discover_and_extract_niche_frameworks", query="!!!")
    assert "letters" in out["error"]
    out = await _call(
        registry,
        "discover_and_extract_niche_frameworks",
        query="ai",
        platform="myspace",
    )
    assert "unknown platform" in out["error"]


async def test_a_linkedin_discovery_is_reported_as_failed_not_faked() -> None:
    from lumi_ai.ports import UnsupportedPlatform

    registry, *_ = _services(
        {h: [] for h in HANDLES}, {"*": UnsupportedPlatform("no linkedin reads")}
    )
    out = await _call(
        registry,
        "discover_and_extract_niche_frameworks",
        query="ai",
        platform="linkedin",
        handles=["alice"],
    )
    assert out["status"] == "failed" and out["frameworks"] == []


async def test_advice_without_a_report_says_so() -> None:
    registry, *_ = _services()
    out = await _call(registry, "get_peer_advice", topic="launch")
    assert "no niche analysis" in out["error"]


async def test_advice_returns_ranked_frameworks_and_peer_examples() -> None:
    registry, *_ = _services(with_rag=True)
    await _call(
        registry,
        "discover_and_extract_niche_frameworks",
        query="ai tools",
        handles=HANDLES,
    )
    out = await _call(registry, "get_peer_advice", topic="alice post second line")
    assert out["status"] == "ok" and out["frameworks"]
    assert all("relevance" in f for f in out["frameworks"])
    assert (
        out["examples"]
        and out["examples"][0]["distance"] <= out["examples"][-1]["distance"]
    )
    assert len(out["examples"]) <= CTX.config.peer_advice_max_items


async def test_advice_refuses_to_advise_from_an_insufficient_report() -> None:
    registry, *_ = _services({h: make_posts(h, winners=0) for h in HANDLES})
    await _call(
        registry, "discover_and_extract_niche_frameworks", query="ai", handles=HANDLES
    )
    out = await _call(registry, "get_peer_advice", topic="launch")
    assert out["status"] == "insufficient_data" and out["frameworks"] == []
    assert "error" in out and out["detail"]


async def test_pasted_post_is_tagged_and_compared_with_the_niche() -> None:
    llm = TaggerLLM(pas_ids=[f"{h}-{i}" for h in HANDLES for i in range(10)])
    registry, _, _, _, _, llm = _services(llm=llm)
    text = "Nobody told me this.\nI lost a year doing it wrong."
    first = await _call(registry, "analyze_pasted_post", text=text)
    assert first["niche_comparison"] == "no niche analysis to compare against"
    assert first["post_ref"].startswith("x:pasted-")
    assert first["primary_framework"] == "hot_take"
    await _call(
        registry, "discover_and_extract_niche_frameworks", query="ai", handles=HANDLES
    )
    second = await _call(registry, "analyze_pasted_post", text=text)
    assert second["post_ref"] == first["post_ref"]  # same text, same ref
    cmp = second["niche_comparison"]
    assert cmp["matches_niche_framework"] is False and cmp["niche_frameworks"] == [
        "pas"
    ]


async def test_pasted_post_failures_are_errors_not_analyses() -> None:
    registry, *_ = _services(llm=TaggerLLM(broken=True))
    out = await _call(registry, "analyze_pasted_post", text="hello there")
    assert "could not analyse" in out["error"]
    out = await _call(registry, "analyze_pasted_post", text="   ")
    assert out["error"] == "no post text to analyse"


async def test_the_pasted_post_never_hits_the_network() -> None:
    registry, _, social, *_ = _services()
    await _call(registry, "analyze_pasted_post", text="a post")
    assert social.calls == []


async def test_trends_keep_viral_posts_once_and_default_to_the_niche_handles() -> None:
    registry, _, social, _, peers, _ = _services(
        {"peer_one": make_posts("peer_one", 10, winners=0)},
        tracked={"x": ("Peer_One",)},
    )
    out = await _call(registry, "check_niche_trends", min_likes=20)
    assert out["new_matches_found"] == 10 and out["scanned_handles"] == {"peer_one": 10}
    assert social.calls[0][1] == "peer_one"
    again = await _call(registry, "check_niche_trends")
    assert again["new_matches_found"] == 0  # the same posts are not matched twice
    assert len(peers.rows) == 10
    assert all(r.niche_key == "ai:global" for r in peers.rows.values())


async def test_viral_posts_carry_the_photo_the_source_gave_and_an_empty_string_otherwise() -> (
    None
):
    posts = make_posts("peer_one", 2, winners=0)
    with_photo = replace(posts[0], author_avatar_url="https://cdn.example/peer_one.jpg")
    registry, _, _, _, peers, _ = _services({"peer_one": [with_photo, posts[1]]})
    out = await _call(registry, "check_niche_trends", handles=["peer_one"])
    by_url = {p["url"]: p["avatar_url"] for p in out["viral_posts"]}
    assert by_url[with_photo.url] == "https://cdn.example/peer_one.jpg"
    assert by_url[posts[1].url] == ""  # unknown: empty, never invented
    assert {r.author_avatar_url for r in peers.rows.values()} == {
        "https://cdn.example/peer_one.jpg",
        "",
    }


async def test_trends_threshold_and_missing_likes() -> None:
    registry, *_ = _services({"peer_one": make_posts("peer_one", 4, winners=0)})
    out = await _call(
        registry, "check_niche_trends", handles=["peer_one"], min_likes="31"
    )
    assert out["min_likes"] == 31 and out["new_matches_found"] == 0  # likes are 30
    out = await _call(
        registry, "check_niche_trends", handles=["peer_one"], min_likes="many"
    )
    assert out["min_likes"] == 20 and out["new_matches_found"] == 4


async def test_trends_need_accounts_and_say_when_nothing_could_be_read() -> None:
    registry, *_ = _services()
    out = await _call(registry, "check_niche_trends")
    assert "no accounts to check" in out["error"]
    registry, *_ = _services({}, {"*": BudgetExceeded("over")})
    out = await _call(registry, "check_niche_trends", handles=["a", "b"])
    assert "no account could be read" in out["error"] and out["new_matches_found"] == 0


async def test_own_lift_tool_and_registration_by_port() -> None:
    posts = [
        PostOut(
            i,
            1,
            "x",
            f"p{i}",
            f"t{i}",
            NOW.replace(day=20, hour=i % 20),
            "original",
            metrics=PostMetrics(views=1000 + i, likes=1),
        )
        for i in range(30)
    ]
    registry, *_ = _services(own=posts)
    out = await _call(registry, "get_own_lift")
    assert out["status"] == "insufficient_data" and out["n_eligible"] == 30
    assert "get_own_lift" in registry.names
    without, *_ = _services()
    with pytest.raises(ValueError, match="unknown tool"):
        await _call(without, "get_own_lift")
    assert "get_own_lift" not in without.names
    assert "check_niche_trends" in without.names
