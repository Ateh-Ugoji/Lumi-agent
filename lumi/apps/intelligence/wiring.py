"""Builds the agent, its stores and its providers from the environment. Nothing is simulated.

``AIConfig.from_env()`` is read once. A missing key leaves the matching provider out of the chain
and its probe red in ``check_keys``; it never swaps in a canned answer. Tools whose port has no
implementation are simply not registered; ``connect_account`` (``DjangoConnectionLinks``) and
``backfill_posts`` (``DjangoOwnPostSync``) are wired.
"""

from __future__ import annotations

import contextvars
import functools
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from asgiref.sync import sync_to_async

from apps.connections import mcp_gateway
from apps.connections.connect_links import DjangoConnectionLinks
from apps.connections.own_post_sync import DjangoOwnPostSync
from apps.intelligence import repos
from lumi_ai.agent.loop import AgentDeps, AgentLoop
from lumi_ai.competitors import tools as competitor_tools
from lumi_ai.competitors.pipeline import PipelineDeps
from lumi_ai.competitors.tools import CompetitorServices
from lumi_ai.config import AIConfig
from lumi_ai.evaluation.evaluator import Evaluator
from lumi_ai.evaluation.reviewer import QualityReviewer
from lumi_ai.evaluation.rubric import JevScorer, LLMScorer
from lumi_ai.evaluation.style import StyleReferencer
from lumi_ai.generation import tools as generation_tools
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.enforcement import EnforcementReviewer
from lumi_ai.generation.flow import GenerationService
from lumi_ai.judge.jev import JevJudge
from lumi_ai.ports import OwnPostSync, Platform, PostIn, SocialData, UserInfo
from lumi_ai.providers.chain import LLMChain
from lumi_ai.providers.factory import build_chain, loop_local
from lumi_ai.rag import tools as rag_tools
from lumi_ai.rag.embedder import OnnxMiniLMEmbedder
from lumi_ai.rag.extractor import LLMMemoryExtractor
from lumi_ai.rag.indexer import VectorIndexer
from lumi_ai.rag.memory import MemoryService
from lumi_ai.rag.retrieval import Retriever
from lumi_ai.rag.vector_store import ChromaVectorStore, make_client
from lumi_ai.style import tools as style_tools
from lumi_ai.style.service import StyleService
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolRegistry
from lumi_ai.video import build_video_analyzer
from lumi_ai.video import tools as video_tools


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


# -- the Xpoz budget is per run ------------------------------------------------------------------

_run_profile: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "lumi_run_profile", default=None
)
_run_social: contextvars.ContextVar[dict[str, SocialData] | None] = (
    contextvars.ContextVar("lumi_run_social", default=None)
)


def begin_run(profile_id: int) -> None:
    """Start a run (one chat turn or one scan): a fresh credit meter, charged to the profile's owner."""
    _run_profile.set(profile_id)
    _run_social.set({})


@sync_to_async
def _owner_id(profile_id: int) -> int | None:
    from apps.profiles.models import SocialProfile

    return (
        SocialProfile.objects.filter(pk=profile_id)
        .values_list("user_id", flat=True)
        .first()
    )


class RunSocialData:
    """``SocialData`` whose Xpoz client (and so its credit meter) lives as long as one run."""

    async def _data(self) -> SocialData:
        from apps.connections.accounts import get_config
        from apps.connections.clients.xpoz import XpozClient
        from apps.connections.socialdata import XpozSocialData
        from apps.connections.stores import DjangoCreditLedger

        profile_id = _run_profile.get()
        cache = _run_social.get()
        if cache is not None and "xpoz" in cache:
            return cache["xpoz"]
        user_id = await _owner_id(profile_id) if profile_id is not None else None
        data = XpozSocialData(
            XpozClient(
                get_config(),
                ledger=DjangoCreditLedger(user_id),
                run_id=f"turn-{uuid.uuid4().hex[:12]}",
            )
        )
        if cache is not None:
            cache["xpoz"] = data
        return data

    async def fetch_user_posts(
        self, platform: Platform, handle: str, since: datetime | None, limit: int
    ) -> list[PostIn]:
        return await (await self._data()).fetch_user_posts(
            platform, handle, since, limit
        )

    async def search_posts(
        self, platform: Platform, query: str, limit: int
    ) -> list[PostIn]:
        return await (await self._data()).search_posts(platform, query, limit)

    async def get_user(self, platform: Platform, handle: str) -> UserInfo | None:
        return await (await self._data()).get_user(platform, handle)

    async def search_users(
        self, platform: Platform, query: str, limit: int
    ) -> list[UserInfo]:
        return await (await self._data()).search_users(platform, query, limit)


# -- everything else ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Wiring:
    config: AIConfig
    chain: LLMChain
    judge: JevJudge
    registry: ToolRegistry
    loop: AgentLoop
    generation: GenerationService
    style: StyleService
    memory: MemoryService
    indexer: VectorIndexer
    retriever: Retriever
    posts: repos.PostRepo
    post_sync: OwnPostSync


@functools.lru_cache(maxsize=1)
def get_wiring() -> Wiring:
    config = AIConfig.from_env()
    chain = build_chain(config, client_factory=loop_local())
    judge = JevJudge(config)
    clock = SystemClock()

    profiles, posts, peers = repos.ProfileRepo(), repos.PostRepo(), repos.PeerPostRepo()
    voice, reports, memory_store = (
        repos.VoiceRepo(),
        repos.ReportRepo(),
        repos.MemoryRepo(),
    )
    chat, turns, repurpose = (
        repos.ChatRepo(),
        repos.TurnLogRepo(),
        repos.RepurposeRepo(),
    )

    embedder = OnnxMiniLMEmbedder()
    vectors = ChromaVectorStore(make_client(config), embedder.name)
    indexer = VectorIndexer(embedder, vectors)
    retriever = Retriever(
        embedder, vectors, posts=posts, peers=peers, memory=memory_store
    )

    memory = MemoryService(memory_store, indexer, retriever, clock, config)
    extractor = LLMMemoryExtractor(chain, memory, memory_store, config)
    style = StyleService(chain, posts, voice, config)

    scorers = []
    if judge.available:
        scorers.append(JevScorer(judge))
    if chain.providers:
        scorers.append(LLMScorer(chain))
    evaluator = Evaluator(scorers, config, style=StyleReferencer(retriever))
    reviewer = QualityReviewer(
        EnforcementReviewer(judge if judge.available else None, config), evaluator
    )
    generation = GenerationService(
        chain,
        ContextBuilder(voice, retriever=retriever, reports=reports, embedder=embedder),
        reviewer,
        repurpose,
        judge=judge if judge.available else None,
    )

    # Off (None) unless VIDEO_PROVIDER and VIDEO_API_KEY are set; then the pipeline is unchanged.
    video = build_video_analyzer(config)
    video_store = repos.VideoRepo()

    competitors = CompetitorServices(
        pipeline=PipelineDeps(
            social=RunSocialData(),
            llm=chain,
            reports=reports,
            peer_posts=peers,
            config=config,
            index_peer_posts=indexer.index_peer_posts,
            video=video,
            video_store=video_store,
        ),
        profiles=profiles,
        posts=posts,
        matches=repos.MatchRepo(),
        embedder=embedder,
        retriever=retriever,
        handles=repos.HandleBookRepo(),
        listening=repos.ListeningRepo(),
    )
    # CONNECT's gateway: connector tools for the registry and ``resolve_pending`` before each turn.
    gateway = mcp_gateway.build_mcp_gateway()
    post_sync = DjangoOwnPostSync()
    registry = build_registry(
        ToolDeps(
            profiles=profiles,
            posts=posts,
            voice=voice,
            reports=reports,
            requests=repos.RequestRepo(),
            listening=repos.ListeningRepo(),
            repurpose=repurpose,
            links=DjangoConnectionLinks(),
            post_sync=post_sync,
        ),
        gateway,
        extra=[
            *generation_tools.build(generation, posts),
            *rag_tools.build(memory),
            *style_tools.build(style),
            *competitor_tools.build(competitors),
            *video_tools.build(video, video_store, config),
        ],
    )
    loop = AgentLoop(
        AgentDeps(
            llm=chain,
            registry=registry,
            chat=chat,
            profiles=profiles,
            clock=clock,
            config=config,
            memory=memory_store,
            turns=turns,
            judge=judge if judge.available else None,
            mcp=gateway,
            memory_extractor=extractor,
        )
    )
    return Wiring(
        config,
        chain,
        judge,
        registry,
        loop,
        generation,
        style,
        memory,
        indexer,
        retriever,
        posts,
        post_sync,
    )
