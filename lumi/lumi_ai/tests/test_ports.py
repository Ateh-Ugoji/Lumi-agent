"""The ports must import without optional dependencies and stay structurally sound."""

from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime

from lumi_ai import ports
from lumi_ai.agent.result import SSEEvent, TurnResult
from lumi_ai.config import AIConfig

STORES = [
    ports.ProfileStore,
    ports.PostStore,
    ports.PeerPostStore,
    ports.VoiceStore,
    ports.ReportStore,
    ports.MemoryStore,
    ports.ChatStore,
    ports.TurnLogStore,
    ports.RepurposeStore,
    ports.RequestStore,
    ports.ListeningStore,
    ports.EvalStore,
]
GATEWAYS = [
    ports.SocialData,
    ports.McpGateway,
    ports.ConnectionLinks,
    ports.VideoAnalyzer,
    ports.SemanticJudge,
    ports.OwnPostSync,
]


def test_every_method_of_a_store_or_gateway_is_async() -> None:
    for proto in STORES + GATEWAYS + [ports.KeyProbe]:
        for name, member in inspect.getmembers(proto, inspect.isfunction):
            if name.startswith("_"):
                continue
            assert inspect.iscoroutinefunction(member), (
                f"{proto.__name__}.{name} must be async"
            )


def test_vector_ports_are_synchronous() -> None:
    for proto in (ports.Embedder, ports.VectorStore, ports.Clock):
        for name, member in inspect.getmembers(proto, inspect.isfunction):
            if not name.startswith("_"):
                assert not inspect.iscoroutinefunction(member), (
                    f"{proto.__name__}.{name}"
                )


def test_every_public_method_has_a_docstring() -> None:
    for proto in (
        STORES
        + GATEWAYS
        + [ports.Embedder, ports.VectorStore, ports.Clock, ports.KeyProbe]
    ):
        assert proto.__doc__, proto.__name__
        for name, member in inspect.getmembers(proto, inspect.isfunction):
            if not name.startswith("_"):
                assert member.__doc__, f"{proto.__name__}.{name} needs a docstring"


def test_dataclasses_are_frozen() -> None:
    for name, obj in vars(ports).items():
        if dataclasses.is_dataclass(obj) and isinstance(obj, type):
            assert obj.__dataclass_params__.frozen, f"{name} must be frozen"


def test_error_hierarchy() -> None:
    for exc in (
        ports.BudgetExceeded,
        ports.ProviderUnavailable,
        ports.RateLimited,
        ports.ProviderAuthError,
        ports.LiveDisabled,
        ports.UnsupportedPlatform,
    ):
        assert issubclass(exc, ports.SocialDataError)
    err = ports.BudgetExceeded("over", provider="xpoz", spent=12, budget=10)
    assert (err.provider, err.spent, err.budget) == ("xpoz", 12, 10)
    assert ports.RateLimited("slow", retry_after_seconds=3).retry_after_seconds == 3


def test_a_minimal_social_data_satisfies_the_protocol() -> None:
    class Impl:
        async def fetch_user_posts(self, platform, handle, since, limit):
            return []

        async def search_posts(self, platform, query, limit):
            return []

        async def get_user(self, platform, handle):
            return None

        async def search_users(self, platform, query, limit):
            return []

    assert isinstance(Impl(), ports.SocialData)
    assert not isinstance(object(), ports.SocialData)


def test_missing_metrics_default_to_none_not_zero() -> None:
    m = ports.PostMetrics()
    assert all(getattr(m, f.name) is None for f in dataclasses.fields(m))
    post = ports.PostIn(
        platform="x", external_id="1", text="hi", published_at=datetime.now(UTC)
    )
    assert post.metrics == ports.PostMetrics()


def test_sse_event_wire_format_matches_legacy() -> None:
    event = SSEEvent(
        "tool_start", {"tool": "get_posts", "arguments": {"limit": 3}, "reason": "r"}
    )
    assert event.as_dict() == {
        "type": "tool_start",
        "tool": "get_posts",
        "arguments": {"limit": 3},
        "reason": "r",
    }
    assert event.encode().startswith('data: {"type": "tool_start"')
    assert event.encode().endswith("\n\n")
    assert TurnResult(content="x").path_taken == "full"


def test_ai_config_from_mapping() -> None:
    cfg = AIConfig.from_mapping(
        {"groq_api_key": "k", "video_provider": "", "max_tool_iterations": 3}
    )
    assert (
        cfg.max_tool_iterations == 3
        and cfg.video_provider is None
        and cfg.groq_api_key == "k"
    )
    try:
        AIConfig.from_mapping({"nope": 1})
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("unknown keys must raise")
