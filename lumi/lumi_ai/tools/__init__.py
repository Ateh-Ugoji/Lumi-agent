"""Agent tools. ``build_registry`` registers every tool whose ports were provided."""

from __future__ import annotations

from lumi_ai.ports import McpGateway
from lumi_ai.tools import account, actions, data, listening, user_requests, voice
from lumi_ai.tools.deps import ToolDeps
from lumi_ai.tools.registry import ToolContext, ToolRegistry, ToolSpec


def build_registry(
    deps: ToolDeps,
    mcp: McpGateway | None = None,
    *,
    extra: list[ToolSpec] | None = None,
) -> ToolRegistry:
    """Register the tools backed by the ports in ``deps``.

    A tool without its port is not registered at all: the model is never offered something that
    cannot run, and nothing answers with a stub. ``extra`` carries tools from later modules
    (RAG memory, competitors, generation) that bring their own services.
    """
    registry = ToolRegistry(mcp)
    if deps.posts is not None:
        registry.register_all(data.build(deps.posts))
    if deps.links is not None:
        registry.register(account.build_connect(deps.links, deps.profiles))
    if deps.post_sync is not None:
        registry.register(account.build_backfill(deps.post_sync))
    if deps.requests is not None:
        registry.register(
            user_requests.build(deps.requests, deps.profiles, deps.reports)
        )
    if deps.voice is not None:
        registry.register_all(voice.build(deps.voice))
    if deps.listening is not None:
        registry.register_all(listening.build(deps.listening))
    if deps.repurpose is not None:
        registry.register(actions.build(deps.repurpose))
    registry.register_all(extra or [])
    return registry


__all__ = ["ToolContext", "ToolDeps", "ToolRegistry", "ToolSpec", "build_registry"]
