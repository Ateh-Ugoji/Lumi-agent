"""The agent loop: one user message in, one reply out, tools in between.

Behaviour ported from ``lumi/legacy/app/agent/loop.py``; the wiring is new. Every collaborator is an
injected port, there is no module-level state and no Django import. The Django glue
(``apps.intelligence.runtime``) builds an :class:`AgentLoop` once and calls :meth:`run_turn`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from lumi_ai import cancel
from lumi_ai.agent import gates
from lumi_ai.agent.context import (
    build_tools_note,
    clip_tool_content,
    estimate_tokens,
    fit_messages,
    slim_for_context,
)
from lumi_ai.agent.prompts import build_fast_prompt, build_system_prompt
from lumi_ai.agent.result import SSEEvent, ToolExecution, TurnResult, shipped_result
from lumi_ai.agent.support import (
    Completer,
    TimedJudge,
    continue_truncated,
    enough_information,
    extract_sample_posts,
    malformed_arguments_message,
    memory_worthy,
    parse_tool_arguments,
    timeout_after_write_message,
    timeout_message,
    tool_failed,
    tool_failure_message,
)
from lumi_ai.agent.turn_class import (
    FREE_TIER_CLASSES,
    allowed_for,
    classify_turn,
    is_greeting_only,
    log_hash,
    log_preview,
)
from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    ChatMessageIn,
    ChatStore,
    Clock,
    McpGateway,
    McpPendingResolution,
    McpToolSpec,
    MemoryStore,
    ProfileInfo,
    ProfileStore,
    SemanticJudge,
    TurnLogStore,
    TurnRecord,
)
from lumi_ai.tools.registry import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

EventSink = Callable[[SSEEvent], Awaitable[None]]

FALLBACK_REPLY = "I ran into trouble completing that — could you try rephrasing?"
CONFIRMED_REASON = "user confirmed the pending write"


class ProfileNotFound(LookupError):
    """The profile does not exist or the caller may not use it. No message is stored."""


class MemoryExtractor(Protocol):
    """Pulls durable facts out of a finished turn and stores them (T6)."""

    async def extract(self, profile_id: int, user_message: str, reply: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AgentDeps:
    llm: Completer
    registry: ToolRegistry
    chat: ChatStore
    profiles: ProfileStore
    clock: Clock
    config: AIConfig = field(default_factory=AIConfig)
    memory: MemoryStore | None = None
    turns: TurnLogStore | None = None
    judge: SemanticJudge | None = None
    mcp: McpGateway | None = None
    memory_extractor: MemoryExtractor | None = None


class AgentLoop:
    """Runs turns. Holds the background tasks it starts so they are not garbage collected."""

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        self._background: set[asyncio.Task[None]] = set()

    async def run_turn(
        self,
        profile_id: int,
        user_message: str,
        on_event: EventSink | None = None,
    ) -> TurnResult:
        deps = self.deps
        profile = await deps.profiles.get_profile(profile_id)
        if profile is None:
            raise ProfileNotFound(f"profile {profile_id} not found")
        message_id = await deps.chat.append(
            profile_id, ChatMessageIn(role="user", content=user_message)
        )
        turn = _Turn(self, profile, user_message, message_id, on_event)
        result = await turn.run()
        self._spawn(self._extract_memories(profile_id, user_message, result.content))
        return result

    async def drain(self) -> None:
        """Wait for background work (memory extraction, turn log). For shutdown and tests."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    def _spawn(self, coro: Awaitable[None]) -> None:
        try:
            task = asyncio.ensure_future(coro)
        except Exception as exc:  # noqa: BLE001 - never touches the turn
            logger.debug("could not schedule background task: %s", exc)
            return
        self._background.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            self._background.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.warning("background task failed: %s", t.exception())

        task.add_done_callback(_done)

    async def _extract_memories(
        self, profile_id: int, user_message: str, reply: str
    ) -> None:
        extractor = self.deps.memory_extractor
        if extractor is None or not reply.strip():
            return
        if not await memory_worthy(
            self.deps.judge, self.deps.config, user_message, reply
        ):
            logger.info("memory gate: skipping extraction")
            return
        await extractor.extract(profile_id, user_message, reply)

    async def _record_turn(self, record: TurnRecord) -> None:
        if self.deps.turns is None:
            return
        try:
            await self.deps.turns.record_turn(record)
        except Exception as exc:  # noqa: BLE001 - a failed audit write never touches the turn
            # Type only: a database error can quote the row, which holds a message preview.
            logger.warning("turn log write failed: %s", type(exc).__name__)


class _Turn:
    """State of one turn. Created per message, so nothing leaks between turns."""

    def __init__(
        self,
        loop: AgentLoop,
        profile: ProfileInfo,
        user_message: str,
        user_message_id: int,
        on_event: EventSink | None,
    ) -> None:
        self.loop = loop
        self.deps = loop.deps
        self.cfg = loop.deps.config
        self.profile = profile
        self.pid = profile.id
        self.user_message = user_message
        self.user_message_id = user_message_id
        self.on_event = on_event
        self.judge = TimedJudge(loop.deps.judge) if loop.deps.judge else None

        self.t0 = time.perf_counter()
        self.tool_calls_made: list[str] = []
        self.executions: list[ToolExecution] = []
        self.completion_ms: list[float] = []
        self.models_seen: list[str] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.tool_ms = 0.0
        self.mcp_ms = 0.0
        self.classify_ms = 0.0
        self.prompt_ms = 0.0
        self.classification = None
        self.path = "full"

    # -- events ---------------------------------------------------------------

    async def _emit(self, type_: str, data: Mapping[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            await self.on_event(SSEEvent(type_, data))  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - a broken listener never kills the turn
            logger.warning("event sink failed on %s: %s", type_, exc)

    # -- persistence ----------------------------------------------------------

    async def _save(self, message: ChatMessageIn) -> int:
        return await self.deps.chat.append(self.pid, message)

    async def _history(self) -> list[dict[str, Any]]:
        rows = await self.deps.chat.history(self.pid, self.cfg.max_history_messages)
        return [
            {"role": m.role, "content": m.content, "tools_used": m.tools_used}
            for m in rows
            if m.role != "tool" and m.content and m.content.strip()
        ]

    # -- turn -----------------------------------------------------------------

    async def run(self) -> TurnResult:
        deps, cfg = self.deps, self.cfg
        cls = await classify_turn(self.user_message, cfg, self.judge)
        self.classification = cls
        self.classify_ms = (time.perf_counter() - self.t0) * 1000
        allow = allowed_for(cls.final_class)
        history = await self._history()

        resolution = await self._resolve_pending()
        fast = (
            cls.path == "fast"
            and resolution is None
            and not gates.coverage_required(self.user_message)
        )
        self.path = "fast" if fast else "full"
        effort = "low" if cls.final_class in FREE_TIER_CLASSES else None

        messages: list[dict[str, Any]]
        tools: list[dict[str, Any]] = []
        mcp_specs: dict[str, McpToolSpec] = {}
        now = deps.clock.now()
        if fast:
            messages = [
                {
                    "role": "system",
                    "content": build_fast_prompt(self.profile, today=now),
                }
            ]
        else:
            messages = [
                {
                    "role": "system",
                    "content": build_system_prompt(
                        self.profile,
                        today=now,
                        memory_summary=await self._memory_summary(),
                        niche_title=await self._niche_title(),
                    ),
                }
            ]
            if allow.costs and allow.names is None:
                mcp_specs = await self._discover_mcp()
            tools = deps.registry.list_specs(allow.costs, allow.names, mcp_specs)
        if resolution is not None:
            messages.append({"role": "system", "content": resolution.note})
        note = build_tools_note(history)
        if note:
            messages.append({"role": "system", "content": note})
        for entry in history:
            entry.pop("tools_used", None)
        messages.extend(history)
        self.prompt_ms = (time.perf_counter() - self.t0) * 1000

        # Fit boundaries: system prompts are protected, older history is droppable, the newest
        # history entry (this user message) is protected. The fit re-runs before each completion
        # because tool results grow the transcript mid-turn.
        history_start = len(messages) - len(history)
        user_idx = len(messages) - 1 if history else history_start

        greeting_only = is_greeting_only(self.user_message)
        coverage_active = not greeting_only and gates.coverage_required(
            self.user_message
        )
        coverage = {
            h: "not_run" for h in gates.extract_named_handles(self.user_message)
        }
        peers_discovered = False
        frameworks_seen: dict | None = None
        nudge_state: str | None = None  # one corrective nudge per turn
        force_final = False
        ctx = ToolContext(self.pid, cfg)

        for _ in range(cfg.max_tool_iterations):
            if (
                not force_final
                and not greeting_only
                and len(self.tool_calls_made) >= cfg.sufficiency_min_tools
                and await enough_information(
                    self.judge, cfg, self.user_message, messages
                )
            ):
                logger.info(
                    "judge early-exit after %d tool calls", len(self.tool_calls_made)
                )
                force_final = True
            use_tools = [] if (force_final or greeting_only) else tools
            tools_tokens = (
                estimate_tokens(json.dumps(use_tools), cfg.est_chars_per_token)
                if use_tools
                else 0
            )
            user_idx = fit_messages(
                messages, history_start, user_idx, tools_tokens, cfg
            )

            started = time.perf_counter()
            llm_result = await deps.llm.complete(messages, use_tools, effort=effort)
            self.completion_ms.append((time.perf_counter() - started) * 1000)
            self._note_usage(llm_result)
            choice = llm_result.completion.choices[0]
            msg = choice.message

            if not msg.tool_calls:
                reply = msg.content or ""
                finish_reason = getattr(choice, "finish_reason", None)
                not_run = [h for h, s in coverage.items() if s == "not_run"]
                incomplete = [
                    h for h, s in coverage.items() if not s.startswith("scanned")
                ]
                if not greeting_only and nudge_state is None:
                    if gates.should_nudge(
                        self.user_message, reply, bool(self.tool_calls_made)
                    ):
                        logger.info(
                            "claim gate: action claimed with zero tools, nudging"
                        )
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {"role": "user", "content": gates.NO_TOOL_NUDGE}
                        )
                        nudge_state = "claim"
                        continue
                    if (
                        coverage_active
                        and not_run
                        and not gates.DECLINE_RE.search(reply)
                    ):
                        logger.info("coverage gate: %s not scanned, nudging", not_run)
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": gates.COVERAGE_NUDGE.format(
                                    handles=", ".join(f"@{h}" for h in not_run)
                                ),
                            }
                        )
                        nudge_state = "coverage"
                        continue
                if (
                    nudge_state == "claim"
                    and not self.tool_calls_made
                    and gates.should_nudge(self.user_message, reply, False)
                ):
                    logger.warning(
                        "claim gate: still claiming with zero tools, disclaiming"
                    )
                    reply += gates.HONESTY_DISCLAIMER
                if (
                    coverage_active
                    and incomplete
                    and not (
                        gates.DECLINE_RE.search(reply) and not self.tool_calls_made
                    )
                ):
                    reply = gates.FULL_PICTURE_RE.sub("partial picture", reply)
                    if "coverage" not in reply[:400].lower():
                        reply = (
                            gates.coverage_block(
                                coverage, peers_discovered, frameworks_seen
                            )
                            + "\n"
                            + reply
                        )
                if finish_reason == "length":
                    started = time.perf_counter()
                    reply = await continue_truncated(deps.llm, messages, reply)
                    self.completion_ms.append((time.perf_counter() - started) * 1000)
                return await self._finish(reply)

            calls = [
                {
                    "id": c.id,
                    "type": c.type,
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments,
                    },
                }
                for c in msg.tool_calls
            ]
            messages.append(
                {"role": "assistant", "content": msg.content, "tool_calls": calls}
            )
            await self._save(
                ChatMessageIn(
                    role="assistant", content=msg.content or "", tool_calls=calls
                )
            )

            for call in calls:
                name = call["function"]["name"]
                arguments, parse_error = parse_tool_arguments(
                    call["function"]["arguments"]
                )
                if parse_error:
                    logger.warning(
                        "tool %s got malformed arguments: %s", name, parse_error
                    )
                reason = arguments.get("reason")
                await self._emit(
                    "tool_start",
                    {"tool": name, "arguments": arguments, "reason": reason},
                )
                result = await self._run_tool(
                    ctx, name, arguments, parse_error, mcp_specs
                )
                self.tool_calls_made.append(name)

                if coverage_active and isinstance(result, dict):
                    if name == "check_niche_trends":
                        gates.record_scan_coverage(coverage, arguments, result)
                    elif name == "discover_and_extract_niche_frameworks":
                        peers_discovered = True
                    elif name == "get_peer_advice":
                        frameworks_seen = {
                            k: result.get(k)
                            for k in (
                                "found",
                                "niche_title",
                                "source_handles",
                                "age_days",
                            )
                        }

                samples = extract_sample_posts(result)
                self.executions.append(
                    ToolExecution(
                        tool=name,
                        arguments=arguments,
                        reason=reason if isinstance(reason, str) else None,
                        ok=not tool_failed(result),
                        sample_posts=samples,
                        result=shipped_result(name, result),
                    )
                )
                await self._emit("tool_done", {"tool": name, "sample_posts": samples})

                result_text = json.dumps(result, default=str)
                await self._save(
                    ChatMessageIn(
                        role="tool",
                        content=result_text,
                        tool_name=name,
                        tool_call_id=call["id"],
                        reason=reason if isinstance(reason, str) else None,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": clip_tool_content(
                            json.dumps(slim_for_context(name, result), default=str),
                            cfg,
                        ),
                    }
                )

        return await self._finish(FALLBACK_REPLY)

    # -- steps ----------------------------------------------------------------

    async def _resolve_pending(self) -> McpPendingResolution | None:
        """Run or cancel a write parked last turn BEFORE the model speaks."""
        mcp = self.deps.mcp
        if mcp is None:
            return None
        try:
            resolution = await mcp.resolve_pending(self.pid, self.user_message)
        except Exception as exc:  # noqa: BLE001 - the write stays parked; the turn goes on
            logger.warning("pending MCP write resolution failed: %s", exc)
            return None
        if resolution is not None and resolution.tool:
            tool = resolution.tool
            self.tool_calls_made.append(tool)
            result = (
                dict(resolution.result)
                if isinstance(resolution.result, Mapping)
                else None
            )
            self.executions.append(
                ToolExecution(
                    tool=tool,
                    arguments=dict(resolution.arguments),
                    reason=CONFIRMED_REASON,
                    ok=not tool_failed(result),
                    result=shipped_result(tool, result),
                )
            )
            await self._save(
                ChatMessageIn(
                    role="tool",
                    content=json.dumps(resolution.result, default=str),
                    tool_name=tool,
                    reason=CONFIRMED_REASON,
                )
            )
            await self._emit(
                "tool_start",
                {
                    "tool": tool,
                    "arguments": dict(resolution.arguments),
                    "reason": CONFIRMED_REASON,
                },
            )
            await self._emit("tool_done", {"tool": tool, "sample_posts": []})
        return resolution

    async def _memory_summary(self) -> str:
        if self.deps.memory is None:
            return ""
        try:
            return await self.deps.memory.get_summary(self.pid)
        except Exception as exc:  # noqa: BLE001 - a missing summary only costs context
            logger.warning("memory summary unavailable: %s", exc)
            return ""

    async def _niche_title(self) -> str | None:
        try:
            niche = await self.deps.profiles.get_niche(self.pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("niche unavailable: %s", exc)
            return None
        return niche.title if niche else None

    async def _discover_mcp(self) -> dict[str, McpToolSpec]:
        if self.deps.mcp is None:
            return {}
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(
                self.deps.registry.mcp_specs(self.pid),
                timeout=self.cfg.mcp_discovery_timeout_seconds,
            )
        except TimeoutError:
            logger.warning("MCP discovery timed out; connector tools absent this turn")
            return {}
        finally:
            self.mcp_ms = (time.perf_counter() - started) * 1000

    async def _run_tool(
        self,
        ctx: ToolContext,
        name: str,
        arguments: dict[str, Any],
        parse_error: str | None,
        mcp_specs: Mapping[str, McpToolSpec],
    ) -> Any:
        if parse_error:
            return {"error": malformed_arguments_message(name, parse_error)}
        started = time.perf_counter()
        timeout = self.cfg.tool_timeout_seconds
        spec = self.deps.registry.get(name)
        # A tool that writes gets a token: once it times out (or the turn is cancelled) no write
        # of it may commit, see lumi_ai.cancel.
        if spec is not None:
            writes = spec.writes
        else:  # an MCP tool: a write tool parks its call in the database before the user confirms
            mcp = mcp_specs.get(name) if mcp_specs else None
            writes = mcp is not None and (
                mcp.cost == "write" or mcp.requires_confirmation
            )
        token = cancel.CancelToken() if writes else None
        reset = cancel.current.set(token) if token is not None else None
        try:
            return await asyncio.wait_for(
                self.deps.registry.call(ctx, name, arguments, mcp_specs),
                timeout=timeout,
            )
        except TimeoutError:
            logger.error("tool %s timed out after %gs", name, timeout)
            commits = await asyncio.to_thread(token.cancel) if token else 0
            if commits:
                return {"error": timeout_after_write_message(name, timeout, commits)}
            return {"error": timeout_message(name, timeout)}
        except asyncio.CancelledError:
            if token is not None:
                token.cancel_nowait()
            raise
        except Exception as exc:
            logger.exception("tool %s raised %s", name, type(exc).__name__)
            return {"error": tool_failure_message(name, exc)}
        finally:
            if reset is not None:
                cancel.current.reset(reset)
            self.tool_ms += (time.perf_counter() - started) * 1000

    def _note_usage(self, llm_result: Any) -> None:
        model = getattr(llm_result, "model", None)
        if model and model not in self.models_seen:
            self.models_seen.append(model)
        usage = getattr(llm_result.completion, "usage", None)
        if usage is None:
            return
        self.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        details = getattr(usage, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None) if details else None
        if reasoning:
            self.reasoning_tokens += int(reasoning)

    async def _finish(self, reply: str) -> TurnResult:
        """Save the reply, log the turn in the background, build the result."""
        reply_id = await self._save(
            ChatMessageIn(
                role="assistant",
                content=reply,
                tools_used=tuple(self.tool_calls_made) or None,
            )
        )
        total_ms = (time.perf_counter() - self.t0) * 1000
        # A metric that was not measured stays out of `timings`: absent means NULL, never 0.
        timings: dict[str, Any] = {
            "classify_ms": round(self.classify_ms, 1),
            "prompt_ms": round(self.prompt_ms, 1),
            "total_ms": round(total_ms, 1),
            "completion_ms": round(sum(self.completion_ms), 1),
        }
        if self.mcp_ms > 0:
            timings["mcp_ms"] = round(self.mcp_ms, 1)
        if self.tool_ms > 0:
            timings["tool_ms"] = round(self.tool_ms, 1)
        if self.judge is not None and self.judge.elapsed_ms > 0:
            timings["judge_ms"] = round(self.judge.elapsed_ms, 1)
        if self.models_seen:
            timings["model"] = ",".join(self.models_seen)
        if self.prompt_tokens:
            timings["prompt_tokens"] = self.prompt_tokens
        if self.completion_tokens:
            timings["completion_tokens"] = self.completion_tokens
        if self.reasoning_tokens:
            timings["reasoning_tokens"] = self.reasoning_tokens
        logger.info("turn metrics: %s", timings)

        cls = self.classification
        self.loop._spawn(
            self.loop._record_turn(
                TurnRecord(
                    profile_id=self.pid,
                    message_id=self.user_message_id,
                    message_text_hash=log_hash(self.user_message),
                    message_preview=log_preview(self.user_message),
                    rule_class=cls.rule_class,
                    rule_matched=cls.rule_matched,
                    final_class=cls.final_class,
                    path_taken=self.path,  # type: ignore[arg-type]
                    tools_called=tuple(self.tool_calls_made),
                    judge_called=cls.jev_called,
                    judge_class=cls.jev_class,
                    judge_probs=tuple(cls.jev_probs) if cls.jev_probs else None,
                    judge_confidence=cls.jev_confidence,
                    judge_latency_ms=cls.jev_latency_ms,
                    judge_error=cls.jev_error,
                    total_latency_ms=int(total_ms),
                    timings=timings,
                )
            )
        )
        return TurnResult(
            content=reply,
            tool_calls_made=tuple(self.tool_calls_made),
            tool_executions=tuple(self.executions),
            path_taken=self.path,  # type: ignore[arg-type]
            assistant_message_id=reply_id,
        )
