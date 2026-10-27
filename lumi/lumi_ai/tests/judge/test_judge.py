from __future__ import annotations

from types import SimpleNamespace

from lumi_ai.config import AIConfig
from lumi_ai.judge import FallbackJudge, JevJudge, LLMJudge, build_judge
from lumi_ai.ports import SemanticJudge


class FakeJevClient:
    def __init__(self, answers=None, error: Exception | None = None) -> None:
        self.answers = answers or {}
        self.error = error
        self.calls: list[dict] = []

    async def system_one(self, *, state, questions):
        self.calls.append({"state": state, "questions": questions})
        if self.error:
            raise self.error
        return SimpleNamespace(answers=self.answers)


def noul(v: float):
    return SimpleNamespace(noul=v, choice=None)


def choice(c: str):
    return SimpleNamespace(noul=None, choice=c)


class FakeChain:
    def __init__(self, text: str | Exception) -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, messages, tools, *, model=None, tier=None, effort=None):
        self.calls.append({"messages": messages, "tier": tier, "effort": effort})
        if isinstance(self.text, Exception):
            raise self.text
        msg = SimpleNamespace(content=self.text)
        return SimpleNamespace(
            completion=SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        )


async def test_jev_without_key_abstains_without_calling_anything() -> None:
    judge = JevJudge(AIConfig())
    assert not judge.available
    assert await judge.ask_noul({"a": 1}, {"q": "?"}) is None
    assert await judge.ask_choice({}, "q", "?", {"a": "x"}) is None


async def test_jev_noul_scores_are_floats() -> None:
    client = FakeJevClient({"q": noul(0.8)})
    judge = JevJudge(AIConfig(), client_factory=lambda: client)
    assert await judge.ask_noul({"s": 1}, {"q": "is it?"}) == {"q": 0.8}
    assert client.calls[0]["state"] == {"s": 1}


async def test_jev_failure_returns_none_never_raises() -> None:
    judge = JevJudge(
        AIConfig(), client_factory=lambda: FakeJevClient(error=RuntimeError("boom"))
    )
    assert await judge.ask_noul({}, {"q": "?"}) is None


async def test_jev_choice_must_be_a_known_criterion() -> None:
    ok = JevJudge(AIConfig(), client_factory=lambda: FakeJevClient({"q": choice("a")}))
    assert await ok.ask_choice({}, "q", "?", {"a": "x", "b": "y"}) == "a"
    bad = JevJudge(
        AIConfig(), client_factory=lambda: FakeJevClient({"q": choice("zzz")})
    )
    assert await bad.ask_choice({}, "q", "?", {"a": "x"}) is None


async def test_llm_judge_scores_and_clamps() -> None:
    chain = FakeChain('```json\n{"sufficient": 1.4, "other": 0.2}\n```')
    judge = LLMJudge(chain)  # type: ignore[arg-type]
    scores = await judge.ask_noul({"x": 1}, {"sufficient": "?", "other": "?"})
    assert scores == {"sufficient": 1.0, "other": 0.2}
    assert chain.calls[0]["tier"] == "small"


async def test_llm_judge_partial_or_garbage_is_no_verdict() -> None:
    assert (
        await LLMJudge(FakeChain('{"a": 0.5}')).ask_noul({}, {"a": "?", "b": "?"})
        is None
    )  # type: ignore[arg-type]
    assert await LLMJudge(FakeChain("no json here")).ask_noul({}, {"a": "?"}) is None  # type: ignore[arg-type]
    assert (
        await LLMJudge(FakeChain(RuntimeError("down"))).ask_noul({}, {"a": "?"}) is None
    )  # type: ignore[arg-type]


async def test_llm_judge_choice() -> None:
    judge = LLMJudge(FakeChain('{"choice": "b"}'))  # type: ignore[arg-type]
    assert await judge.ask_choice({}, "q", "?", {"a": "x", "b": "y"}) == "b"


async def test_fallback_uses_next_judge_only_when_previous_abstains() -> None:
    first = JevJudge(
        AIConfig(), client_factory=lambda: FakeJevClient(error=RuntimeError())
    )
    second = LLMJudge(FakeChain('{"q": 0.3}'))  # type: ignore[arg-type]
    assert await FallbackJudge(first, second).ask_noul({}, {"q": "?"}) == {"q": 0.3}
    chain = FakeChain('{"q": 0.3}')
    working = JevJudge(
        AIConfig(), client_factory=lambda: FakeJevClient({"q": noul(0.9)})
    )
    assert await FallbackJudge(working, LLMJudge(chain)).ask_noul({}, {"q": "?"}) == {
        "q": 0.9
    }  # type: ignore[arg-type]
    assert chain.calls == []


async def test_build_judge_with_nothing_configured_abstains() -> None:
    judge = build_judge(AIConfig(), None)
    assert isinstance(judge, SemanticJudge)
    assert await judge.ask_noul({}, {"q": "?"}) is None
