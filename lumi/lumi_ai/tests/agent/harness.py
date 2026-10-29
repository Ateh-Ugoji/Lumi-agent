"""Scripted model and wiring for agent-loop tests (test-only)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from lumi_ai.agent.loop import AgentDeps, AgentLoop
from lumi_ai.config import AIConfig
from lumi_ai.ports import NicheOut, ProfileInfo, TurnRecord
from lumi_ai.providers.chain import LLMResult
from lumi_ai.tests.fakes import NOW, FakeChat
from lumi_ai.tools.registry import ToolRegistry, ToolSpec

REASON = "the user asked for this in their message"


def call(name: str, arguments: dict | str | None = None, call_id: str = "c1") -> dict:
    if arguments is None:
        arguments = {}
    if isinstance(arguments, dict):
        arguments = {"reason": REASON, **arguments}
        arguments = json.dumps(arguments)
    return {"id": call_id, "name": name, "arguments": arguments}


def say(content: str, finish: str = "stop") -> dict:
    return {"content": content, "finish": finish}


def use(*calls: dict, content: str | None = None) -> dict:
    return {"content": content, "calls": list(calls)}


class FakeLLM:
    """Plays a script, one item per completion; records what the model was shown."""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.seen: list[list[dict]] = []
        self.tools_seen: list[list[dict]] = []
        self.efforts: list[str | None] = []

    async def complete(
        self, messages, tools=None, *, model=None, tier=None, effort=None
    ):
        self.seen.append(copy.deepcopy(list(messages)))
        self.tools_seen.append(list(tools or []))
        self.efforts.append(effort)
        if not self.script:
            raise AssertionError(
                "the model was called more times than the script allows"
            )
        item = self.script.pop(0)
        tool_calls = [
            SimpleNamespace(
                id=c["id"],
                type="function",
                function=SimpleNamespace(name=c["name"], arguments=c["arguments"]),
            )
            for c in item.get("calls", [])
        ] or None
        choice = SimpleNamespace(
            message=SimpleNamespace(content=item.get("content"), tool_calls=tool_calls),
            finish_reason=item.get("finish", "tool_calls" if tool_calls else "stop"),
        )
        usage = SimpleNamespace(
            prompt_tokens=100, completion_tokens=20, completion_tokens_details=None
        )
        completion = SimpleNamespace(choices=[choice], usage=usage, model="fake-model")
        return LLMResult(completion, "fake", "fake-model")

    def tool_messages(self, call_index: int) -> list[dict]:
        return [m for m in self.seen[call_index] if m.get("role") == "tool"]

    def system_text(self, call_index: int) -> str:
        return "\n".join(
            m["content"] for m in self.seen[call_index] if m.get("role") == "system"
        )


class Profiles:
    def __init__(self, profile: ProfileInfo | None = None) -> None:
        self.profile = profile or ProfileInfo(
            7, "Ana", "ana", "linkedin", ("linkedin",)
        )

    async def get_profile(self, profile_id):
        return self.profile if profile_id == self.profile.id else None

    async def get_niche(self, profile_id):
        return NicheOut(profile_id, "ai:global", "AI founders", (), {}, "user", NOW)


class Clock:
    def now(self):
        return NOW

    def monotonic(self):
        return 0.0


class Turns:
    def __init__(self, fail: bool = False) -> None:
        self.records: list[TurnRecord] = []
        self.fail = fail

    async def record_turn(self, record):
        if self.fail:
            raise RuntimeError("db down")
        self.records.append(record)
        return len(self.records)

    async def mark_corrected(self, record_id):
        return None


class Memory:
    async def get_summary(self, profile_id):
        return "Prefers short posts."


class Extractor:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    async def extract(self, profile_id, user_message, reply):
        self.calls.append((profile_id, user_message, reply))


class Judge:
    """Answers ask_noul from a function of the questions; ``None`` = no verdict."""

    def __init__(self, answer=None) -> None:
        self.answer = answer
        self.asked: list[dict] = []

    async def ask_noul(self, state, questions):
        self.asked.append(questions)
        return self.answer(questions) if self.answer else None

    async def ask_choice(self, state, name, instructions, criteria):
        return None


def tool(
    name: str,
    handler=None,
    *,
    cost: str = "free",
    parameters: dict | None = None,
) -> ToolSpec:
    async def default(ctx, **kwargs):
        return {"echo": kwargs}

    return ToolSpec(
        name=name,
        description=f"test tool {name}",
        parameters=parameters or {"type": "object", "properties": {}},
        handler=handler or default,
        cost=cost,  # type: ignore[arg-type]
    )


@dataclass
class Rig:
    loop: AgentLoop
    llm: FakeLLM
    chat: FakeChat
    turns: Turns
    extractor: Extractor
    registry: ToolRegistry
    events: list = field(default_factory=list)

    async def run(self, message: str, profile_id: int = 7):
        async def sink(event):
            self.events.append(event)

        result = await self.loop.run_turn(profile_id, message, sink)
        await self.loop.drain()
        return result

    def saved(self, role: str | None = None):
        rows = [m for _, m in self.chat.rows]
        return [m for m in rows if role is None or m.role == role]


def make_rig(
    script: list[dict],
    tools: list[ToolSpec] | None = None,
    *,
    config: AIConfig | None = None,
    history=None,
    judge: Judge | None = None,
    mcp=None,
    turns: Turns | None = None,
    memory: bool = True,
) -> Rig:
    llm = FakeLLM(script)
    chat = FakeChat(history)
    registry = ToolRegistry(mcp=mcp)
    registry.register_all(tools or [])
    extractor = Extractor()
    turn_log = turns or Turns()
    deps = AgentDeps(
        llm=llm,
        registry=registry,
        chat=chat,
        profiles=Profiles(),
        clock=Clock(),
        config=config or AIConfig(),
        memory=Memory() if memory else None,
        turns=turn_log,
        judge=judge,
        mcp=mcp,
        memory_extractor=extractor,
    )
    return Rig(AgentLoop(deps), llm, chat, turn_log, extractor, registry)
