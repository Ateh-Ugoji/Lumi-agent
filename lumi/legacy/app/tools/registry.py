import copy
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Collection
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import neatlogs

logger = logging.getLogger(__name__)

ToolFunc = Callable[..., Awaitable[Any]]

# --- L13 item 3: per-tool cost tier + side-effect tags -------------------------
VALID_COSTS = frozenset({"free", "credits", "llm", "write"})
VALID_SIDE_EFFECTS = frozenset({"none", "writes_db", "writes_index", "external_write"})

# Result-cache TTL by cost tier (seconds), used when a tool doesn't pass an
# explicit `cache_ttl`. `free`/`write` have no entry (0.0) -> never cached;
# an explicit `cache_ttl=0` on a tool disables caching for it too.
DEFAULT_TTL_BY_COST: dict[str, float] = {"credits": 900.0, "llm": 600.0}
_CACHE_MAX_ENTRIES = 256
# (profile_id, tool, normalized args) -> (monotonic timestamp, result).
# Single event loop -> no locks needed.
_result_cache: dict[tuple, tuple[float, Any]] = {}

_current_profile_id: ContextVar[int | None] = ContextVar("current_profile_id", default=None)


def set_current_profile_id(profile_id: int | None) -> None:
    """Scope tools to the chat's real profile for the current agent turn."""
    _current_profile_id.set(profile_id)


def get_current_profile_id() -> int | None:
    return _current_profile_id.get()


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    func: ToolFunc
    # L13 item 3: tier the loop gates on + what a call mutates. Defaults keep
    # direct `ToolSpec(...)` constructions (tests/fixtures) valid and free.
    cost: str = "free"
    side_effects: str = "none"
    # Seconds; 0.0 = never cache this tool's result. Decorator resolves
    # `None` via DEFAULT_TTL_BY_COST at registration time.
    cache_ttl: float = 0.0


_REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    parameters: dict,
    *,
    cost: str = "free",
    side_effects: str = "none",
    cache_ttl: float | None = None,
) -> Callable[[ToolFunc], ToolFunc]:
    """Register an async tool function under `name` with an OpenAI-style JSON schema.

    `cost` is the tier the agent loop gates on (`free`|`credits`|`llm`|`write`),
    `side_effects` declares what a call mutates (`none`|`writes_db`|
    `writes_index`|`external_write`), and `cache_ttl` overrides the result-cache
    TTL in seconds (`None` = per-tier default, `0` disables caching).
    Invalid enums raise at import time so a typo can't ship as a silent default.
    """
    if cost not in VALID_COSTS:
        raise ValueError(f"tool {name}: unknown cost {cost!r} (expected one of {sorted(VALID_COSTS)})")
    if side_effects not in VALID_SIDE_EFFECTS:
        raise ValueError(
            f"tool {name}: unknown side_effects {side_effects!r} (expected one of {sorted(VALID_SIDE_EFFECTS)})"
        )
    resolved_ttl = DEFAULT_TTL_BY_COST.get(cost, 0.0) if cache_ttl is None else float(cache_ttl)

    def decorator(func: ToolFunc) -> ToolFunc:
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
            cost=cost,
            side_effects=side_effects,
            cache_ttl=resolved_ttl,
        )
        return func

    return decorator


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def get_cost(name: str) -> str | None:
    """Cost tier of a tool by name (native or MCP); `None` when unknown.

    Used for the per-turn `tools_used` summary/audit rows.
    """
    spec = _REGISTRY.get(name)
    if spec is not None:
        return spec.cost
    if name.startswith("mcp__"):
        from app.services import mcp as mcp_service

        connector, _ = mcp_service.split_spec_name(name)
        if connector is not None:
            return mcp_service.spec_cost(name)
    return None


# --- L13 item 4: required `reason` on every emitted tool spec ------------------

_REASON_PARAM = {
    "type": "string",
    "description": "Why this tool now, tied to the user's ask, one sentence (20 words max).",
}


def _with_reason(parameters: dict) -> dict:
    """Copy of a tool schema with the required `reason` field injected.

    Injected into *emitted spec copies only* (L13 item 4): the stored
    `ToolSpec.parameters` stays clean so `_validate_arguments` and schema
    assertions never see `reason` — `call_tool` pops it from a copy of the
    arguments before validation (the caller's dict keeps it for SSE/audit).
    """
    out = dict(parameters)
    properties = dict(out.get("properties") or {})
    properties["reason"] = dict(_REASON_PARAM)
    required = list(out.get("required") or [])
    if "reason" not in required:
        required.append("reason")
    out["properties"] = properties
    out["required"] = required
    return out


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
# Words that carry no justification of their own — dropped before comparing a
# reason against the tool's name.
_REASON_FILLER = frozenset(
    {
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
    }
)


def _normalize_words(text: str) -> list[str]:
    return [w for w in _NON_WORD_RE.split((text or "").lower()) if w and w not in _REASON_FILLER]


def _is_tool_name_only(reason: str, tool_name: str) -> bool:
    """True when `reason` is just the tool's own name (plus filler words).

    Empty after filler-stripping (e.g. reason = "the tool") counts as NOT
    name-only: it is vacuous, but it isn't claiming the name is a justification.
    """
    reason_words = _normalize_words(reason)
    if not reason_words:
        return False
    return reason_words == _normalize_words(tool_name)


def _validate_reason(name: str, cost: str, raw: Any) -> str:
    """L13 item 4: every tool call carries a short, real why.

    Non-empty is required for ALL tools (the model is told how to retry).
    `credits`/`write` tools additionally reject a reason that only restates the
    tool's name — spending credits or mutating state needs an actual reason.
    """
    reason = raw.strip() if isinstance(raw, str) else ""
    if not reason:
        raise ValueError(
            f"tool {name} is missing required argument: reason. "
            "Say why this tool now, tied to the user's ask (20 words max). "
            "Retry with the reason filled in."
        )
    if cost in {"credits", "write"} and _is_tool_name_only(reason, name):
        raise ValueError(
            f"tool {name}: reason must explain why this tool serves the user's ask — "
            f"restating the tool's name ({reason!r}) is not a reason. "
            "Retry with a real reason (20 words max)."
        )
    return reason


# --- result cache (credits/llm tools, keyed per profile) -----------------------


def _cache_key(name: str, arguments: dict) -> tuple:
    # profile_id is in both the ContextVar and the key defensively: some tools
    # lack profile_id in their arguments entirely.
    return (
        get_current_profile_id(),
        name,
        json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False),
    )


def _cache_get(key: tuple, ttl: float) -> Any | None:
    entry = _result_cache.get(key)
    if entry is None:
        return None
    stored_at, result = entry
    age = time.monotonic() - stored_at
    if age >= ttl:
        _result_cache.pop(key, None)
        return None
    cached = copy.deepcopy(result)
    if isinstance(cached, dict):
        cached["cache"] = f"cached, {int(age // 60)} min old" if age >= 60 else "cached, <1 min old"
        cached["cache_age_seconds"] = round(age, 1)
    return cached


def _cache_put(key: tuple, result: Any) -> None:
    if isinstance(result, dict) and "error" in result:
        return  # failures are never cached
    if len(_result_cache) >= _CACHE_MAX_ENTRIES and key not in _result_cache:
        oldest = min(_result_cache, key=lambda k: _result_cache[k][0])
        _result_cache.pop(oldest, None)
    _result_cache[key] = (time.monotonic(), copy.deepcopy(result))


# --- spec listing / dispatch ----------------------------------------------------


def list_tool_specs(
    allowed_costs: Collection[str] | None = None,
    allowed_names: Collection[str] | None = None,
) -> list[dict]:
    """OpenAI-style `tools` payload for the chat completions API.

    Native tools come first, then the cached MCP connector specs
    (`mcp__<connector>__<tool>`) — discovery itself is async and runs in the
    background (`app.background.mcp_refresh`); this only reads the cache.

    `allowed_costs` filters by cost tier and `allowed_names` pins an exact
    whitelist (both AND-combined; `None` = keep everything) — the loop's
    per-class tier gate (L13 item 3). An empty collection yields no tools.
    Every emitted spec carries the required `reason` field (L13 item 4).
    """
    from app.services import mcp as mcp_service

    costs = set(allowed_costs) if allowed_costs is not None else None
    names = set(allowed_names) if allowed_names is not None else None

    specs: list[dict] = []
    for spec in _REGISTRY.values():
        if costs is not None and spec.cost not in costs:
            continue
        if names is not None and spec.name not in names:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": _with_reason(spec.parameters),
                },
            }
        )

    for entry in mcp_service.list_specs():
        fn = entry.get("function") or {}
        mcp_name = fn.get("name", "")
        if costs is not None and mcp_service.spec_cost(mcp_name) not in costs:
            continue
        if names is not None and mcp_name not in names:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": mcp_name,
                    "description": fn.get("description", ""),
                    "parameters": _with_reason(fn.get("parameters") or {}),
                },
            }
        )
    return specs


def _with_profile_context(spec: ToolSpec, arguments: dict) -> dict:
    """Auto-fill a missing/None `profile_id` with the current chat profile when the tool accepts one."""
    if "profile_id" not in spec.parameters.get("properties", {}):
        return arguments
    if arguments.get("profile_id") is None:
        current = get_current_profile_id()
        if current is not None:
            return {**arguments, "profile_id": current}
    return arguments


def _validate_arguments(spec: ToolSpec, arguments: dict) -> dict:
    """Enforce the tool's declared schema before dispatch.

    Models hallucinate extra parameters — we have seen `url` passed to
    `get_peer_advice`, which used to abort the whole turn with a bare Python
    `TypeError`. An undeclared key is dropped (never fatal); a *missing*
    required key raises a `ValueError` whose message is written for the model
    to read and correct itself with.
    """
    properties = spec.parameters.get("properties") or {}
    cleaned = {k: v for k, v in arguments.items() if k in properties}

    dropped = sorted(set(arguments) - set(cleaned))
    if dropped:
        logger.warning("tool %s: dropping undeclared argument(s): %s", spec.name, ", ".join(dropped))

    missing = [k for k in (spec.parameters.get("required") or []) if cleaned.get(k) is None]
    if missing:
        raise ValueError(
            f"tool {spec.name} is missing required argument(s): {', '.join(missing)}. "
            f"Declared parameters: {', '.join(properties) or 'none'}. Retry with exactly those."
        )
    return cleaned


async def call_tool(name: str, arguments: dict) -> Any:
    # Copied FIRST: `reason` is popped from this copy only, so the caller's
    # dict (loop.py) keeps it for the SSE tool_start event and the audit row.
    args = dict(arguments or {})
    spec = get_tool(name)

    if spec is None and name.startswith("mcp__"):
        # Connector tool: validate the reason, then hand off to the MCP client
        # (same tracing as a native tool; it applies the write-confirmation gate).
        from app.services import mcp as mcp_service

        reason = args.pop("reason", None)
        connector, _ = mcp_service.split_spec_name(name)
        if connector is None:
            # Unknown connector/tool: forward untouched so the MCP layer raises
            # its own model-facing "unknown MCP tool" error (ordering pinned by
            # tests — reason validation must NOT preempt it).
            return await mcp_service.call_tool(name, args)
        cost = mcp_service.spec_cost(name)
        _validate_reason(name, cost, reason)
        with neatlogs.trace(name, kind="TOOL") as span:
            span.set_attribute("neatlogs.tool.name", name)
            span.set_attribute("tool.arguments", str(args))
            span.set_attribute("tool.reason", reason or "")
            return await mcp_service.call_tool(name, args)

    if spec is None:
        raise ValueError(f"unknown tool: {name}")

    reason = _validate_reason(name, spec.cost, args.pop("reason", None))
    args = _with_profile_context(spec, args)
    args = _validate_arguments(spec, args)

    # TTL cache check happens BEFORE the trace block: a cache hit is not an
    # execution, so it must not produce a tool span.
    cache_key: tuple | None = None
    if spec.cache_ttl > 0:
        cache_key = _cache_key(name, args)
        cached = _cache_get(cache_key, spec.cache_ttl)
        if cached is not None:
            return cached

    with neatlogs.trace(name, kind="TOOL") as span:
        span.set_attribute("neatlogs.tool.name", name)
        span.set_attribute("tool.arguments", str(args))
        span.set_attribute("tool.reason", reason)
        result = await spec.func(**args)

    if cache_key is not None:
        _cache_put(cache_key, result)
    return result
