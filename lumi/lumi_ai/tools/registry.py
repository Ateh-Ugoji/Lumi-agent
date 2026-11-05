"""Tool registry of the agent: specs for the model, validation, caching and dispatch.

Differences from ``lumi/legacy/app/tools/registry.py``:

* No module-level state. A :class:`ToolRegistry` is built per application (or per test) and
  receives its dependencies through :class:`ToolDeps`.
* The profile is fixed by the turn (:class:`ToolContext`). A ``profile_id`` argument sent by the
  model is **ignored and overwritten**: a model must never be able to read another profile's data.
* MCP connector tools come from :class:`~lumi_ai.ports.McpGateway`, not from a global cache.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from lumi_ai.config import AIConfig
from lumi_ai.ports import McpCallResult, McpGateway, McpToolSpec, ToolCost

logger = logging.getLogger(__name__)

VALID_COSTS = frozenset({"free", "credits", "llm", "write"})
VALID_SIDE_EFFECTS = frozenset({"none", "writes_db", "writes_index", "external_write"})
#: Result-cache TTL (seconds) by cost tier when a tool does not set its own.
DEFAULT_TTL_BY_COST: Mapping[str, float] = {"credits": 900.0, "llm": 600.0}
CACHE_MAX_ENTRIES = 256
MCP_PREFIX = "mcp__"


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a tool handler may rely on for one turn."""

    profile_id: int
    config: AIConfig = field(default_factory=AIConfig)


ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A native tool. ``handler(ctx, **arguments)`` returns a JSON-serialisable value."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    cost: ToolCost = "free"
    side_effects: str = "none"
    cache_ttl: float | None = None  # None = per-tier default, 0 = never cached

    def __post_init__(self) -> None:
        if self.cost not in VALID_COSTS:
            raise ValueError(f"tool {self.name}: unknown cost {self.cost!r}")
        if self.side_effects not in VALID_SIDE_EFFECTS:
            raise ValueError(
                f"tool {self.name}: unknown side_effects {self.side_effects!r}"
            )

    @property
    def writes(self) -> bool:
        """True when the tool saves something locally, so its writes must be cancellable."""
        return self.cost == "write" or self.side_effects in {
            "writes_db",
            "writes_index",
        }

    @property
    def ttl(self) -> float:
        if self.cache_ttl is not None:
            return float(self.cache_ttl)
        return DEFAULT_TTL_BY_COST.get(self.cost, 0.0)


# --- required `reason` on every emitted tool spec ----------------------------

_REASON_PARAM = {
    "type": "string",
    "description": "Why this tool now, tied to the user's ask, one sentence (20 words max).",
}


def with_reason(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of a schema with the required ``reason`` field (emitted copies only)."""
    out = dict(parameters)
    properties = dict(out.get("properties") or {})
    properties["reason"] = dict(_REASON_PARAM)
    required = list(out.get("required") or [])
    if "reason" not in required:
        required.append("reason")
    out["type"] = out.get("type", "object")
    out["properties"] = properties
    out["required"] = required
    return out


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_REASON_FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "to",
        "call",
        "calls",
        "calling",
        "run",
        "runs",
        "running",
        "use",
        "uses",
        "using",
        "tool",
        "tools",
        "now",
        "please",
        "for",
    ]
)


def _words(text: str) -> list[str]:
    return [
        w
        for w in _NON_WORD_RE.split((text or "").lower())
        if w and w not in _REASON_FILLER
    ]


def validate_reason(name: str, cost: str, raw: Any) -> str:
    """Every call carries a short, real why. Spending or writing needs more than the tool's name."""
    reason = raw.strip() if isinstance(raw, str) else ""
    if not reason:
        raise ValueError(
            f"tool {name} is missing required argument: reason. "
            "Say why this tool now, tied to the user's ask (20 words max). "
            "Retry with the reason filled in."
        )
    words = _words(reason)
    if cost in {"credits", "write"} and words and words == _words(name):
        raise ValueError(
            f"tool {name}: reason must explain why this tool serves the user's ask — "
            f"restating the tool's name ({reason!r}) is not a reason. "
            "Retry with a real reason (20 words max)."
        )
    return reason


def validate_arguments(spec: ToolSpec, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Drop undeclared keys (never fatal); a missing required key is a model-readable error."""
    properties = spec.parameters.get("properties") or {}
    cleaned = {k: v for k, v in arguments.items() if k in properties}
    dropped = sorted(set(arguments) - set(cleaned))
    if dropped:
        logger.warning(
            "tool %s: dropping undeclared argument(s): %s",
            spec.name,
            ", ".join(dropped),
        )
    required = [k for k in (spec.parameters.get("required") or []) if k != "profile_id"]
    missing = [k for k in required if cleaned.get(k) is None]
    if missing:
        raise ValueError(
            f"tool {spec.name} is missing required argument(s): {', '.join(missing)}. "
            f"Declared parameters: {', '.join(properties) or 'none'}. Retry with exactly those."
        )
    return cleaned


def _mcp_result_to_dict(result: McpCallResult) -> dict[str, Any]:
    out: dict[str, Any] = {"status": result.status, **dict(result.payload)}
    if result.summary:
        out["summary"] = result.summary
    if result.error:
        out["error"] = result.error
    return out


class ToolRegistry:
    """Holds native tools and dispatches native and MCP calls."""

    def __init__(
        self,
        mcp: McpGateway | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._mcp = mcp
        self._clock = clock
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    # -- registration -------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} is already registered")
        if spec.name.startswith(MCP_PREFIX):
            raise ValueError(f"tool name {spec.name!r} is reserved for MCP connectors")
        self._tools[spec.name] = spec

    def register_all(self, specs: Collection[ToolSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def cost_of(
        self, name: str, mcp_specs: Mapping[str, McpToolSpec] | None = None
    ) -> str | None:
        spec = self._tools.get(name)
        if spec is not None:
            return spec.cost
        mcp_spec = (mcp_specs or {}).get(name)
        return mcp_spec.cost if mcp_spec else None

    # -- specs for the model ---------------------------------------------------

    async def mcp_specs(self, profile_id: int) -> dict[str, McpToolSpec]:
        """Tools of the connected MCP connectors. An unreachable gateway means none this turn."""
        if self._mcp is None:
            return {}
        try:
            return {t.name: t for t in await self._mcp.list_tools(profile_id)}
        except Exception as exc:  # noqa: BLE001 - discovery must never kill a turn
            logger.warning(
                "MCP tool discovery failed for profile %s: %s", profile_id, exc
            )
            return {}

    def list_specs(
        self,
        allowed_costs: Collection[str] | None = None,
        allowed_names: Collection[str] | None = None,
        mcp_specs: Mapping[str, McpToolSpec] | None = None,
    ) -> list[dict[str, Any]]:
        """OpenAI-style ``tools`` payload. Costs and names are AND-combined; ``None`` keeps all."""
        costs = set(allowed_costs) if allowed_costs is not None else None
        names = set(allowed_names) if allowed_names is not None else None
        entries: list[tuple[str, str, Mapping[str, Any], str]] = [
            (s.name, s.description, s.parameters, s.cost) for s in self._tools.values()
        ]
        entries += [
            (m.name, m.description, m.parameters, m.cost)
            for m in (mcp_specs or {}).values()
        ]
        out: list[dict[str, Any]] = []
        for name, description, parameters, cost in entries:
            if (costs is not None and cost not in costs) or (
                names is not None and name not in names
            ):
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": with_reason(parameters),
                    },
                }
            )
        return out

    # -- dispatch -----------------------------------------------------------------

    def _cache_key(
        self, ctx: ToolContext, name: str, args: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        return (
            ctx.profile_id,
            name,
            json.dumps(args, sort_keys=True, default=str, ensure_ascii=False),
        )

    def _cache_get(self, key: tuple[Any, ...], ttl: float) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, result = entry
        age = self._clock() - stored_at
        if age >= ttl:
            self._cache.pop(key, None)
            return None
        cached = copy.deepcopy(result)
        if isinstance(cached, dict):
            cached["cache"] = (
                f"cached, {int(age // 60)} min old"
                if age >= 60
                else "cached, <1 min old"
            )
            cached["cache_age_seconds"] = round(age, 1)
        return cached

    def _cache_put(self, key: tuple[Any, ...], result: Any) -> None:
        if isinstance(result, dict) and "error" in result:
            return  # failures are never cached
        if len(self._cache) >= CACHE_MAX_ENTRIES and key not in self._cache:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            self._cache.pop(oldest, None)
        self._cache[key] = (self._clock(), copy.deepcopy(result))

    async def call(
        self,
        ctx: ToolContext,
        name: str,
        arguments: Mapping[str, Any] | None,
        mcp_specs: Mapping[str, McpToolSpec] | None = None,
    ) -> Any:
        """Run one tool call. Raises ``ValueError`` with a model-readable message on bad input."""
        args = dict(arguments or {})  # `reason` is popped from this copy only
        spec = self._tools.get(name)

        if spec is None and name.startswith(MCP_PREFIX):
            return await self._call_mcp(ctx, name, args, mcp_specs or {})
        if spec is None:
            raise ValueError(f"unknown tool: {name}")

        validate_reason(name, spec.cost, args.pop("reason", None))
        if "profile_id" in (spec.parameters.get("properties") or {}):
            args["profile_id"] = ctx.profile_id  # the turn decides, never the model
        args = validate_arguments(spec, args)

        key: tuple[Any, ...] | None = None
        if spec.ttl > 0:
            key = self._cache_key(ctx, name, args)
            cached = self._cache_get(key, spec.ttl)
            if cached is not None:
                return cached

        result = await spec.handler(
            ctx, **{k: v for k, v in args.items() if k != "profile_id"}
        )
        if key is not None:
            self._cache_put(key, result)
        return result

    async def _call_mcp(
        self,
        ctx: ToolContext,
        name: str,
        args: dict[str, Any],
        mcp_specs: Mapping[str, McpToolSpec],
    ) -> Any:
        reason = args.pop("reason", None)
        spec = mcp_specs.get(name)
        if self._mcp is None or spec is None:
            raise ValueError(
                f"unknown MCP tool: {name}. The connector is not connected for this profile."
            )
        validate_reason(name, spec.cost, reason)
        result = await self._mcp.call(ctx.profile_id, name, args)
        return _mcp_result_to_dict(result)
