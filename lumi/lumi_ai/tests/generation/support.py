"""Doubles for the generation tests (test-only)."""

from __future__ import annotations

import json

from lumi_ai.agent.support import Completer  # noqa: F401  (documents what FakeLLM stands in for)
from lumi_ai.generation.types import GenerationBrief


def reply(text: str, changes: list[dict] | None = None) -> dict:
    """A well-formed writer reply."""
    from lumi_ai.tests.agent.harness import say

    return say(json.dumps({"text": text, "changes": changes or []}))


class FakeJudge:
    """A SemanticJudge that plays scripted answers; ``None`` means no verdict."""

    def __init__(self, noul=None, choice=None):
        self.noul = list(noul or [])
        self.choice = list(choice or [])
        self.noul_calls: list[tuple[dict, dict]] = []
        self.choice_calls: list[tuple[dict, str]] = []

    async def ask_noul(self, state, questions):
        self.noul_calls.append((state, questions))
        return self.noul.pop(0) if self.noul else None

    async def ask_choice(self, state, name, instructions, criteria):
        self.choice_calls.append((state, name))
        return self.choice.pop(0) if self.choice else None


def brief(**kw) -> GenerationBrief:
    base = {
        "profile_id": 1,
        "platform": "linkedin",
        "mode": "repurpose",
        "source_text": "We shipped the new dashboard today. See https://acme.io/new @acme",
    }
    base.update(kw)
    return GenerationBrief(**base)


class TierLLM:
    """A FakeLLM that also records the tier each call asked for."""

    def __init__(self, script):
        from lumi_ai.tests.agent.harness import FakeLLM

        self.inner = FakeLLM(script)
        self.tiers: list[str | None] = []

    @property
    def seen(self):
        return self.inner.seen

    async def complete(
        self, messages, tools=None, *, model=None, tier=None, effort=None
    ):
        self.tiers.append(tier)
        return await self.inner.complete(
            messages, tools, model=model, tier=tier, effort=effort
        )


class StubRetriever:
    """Returns the same posts for any query; records the calls."""

    def __init__(self, own=(), anywhere=(), error: Exception | None = None):
        from lumi_ai.rag.retrieval import Recalled

        self._recalled = Recalled
        self.own = list(own)
        self.anywhere = list(anywhere)
        self.error = error
        self.calls: list[dict] = []

    async def similar_posts(self, profile_id, query, k=5, *, platform=None):
        self.calls.append({"query": query, "k": k, "platform": platform})
        if self.error:
            raise self.error
        rows = self.own if platform else self.anywhere
        return [self._recalled(p, 0.2) for p in rows[:k]]


def voice_out(platform=None, version=3, **payload):
    from lumi_ai.ports import VoiceProfileOut
    from lumi_ai.tests.fakes import NOW

    base = {
        "archetype_name": "The Builder",
        "tone": "plain and warm",
        "emoji_use": "never",
    }
    return VoiceProfileOut(
        id=version,
        profile_id=1,
        platform=platform,
        version=version,
        payload={**base, **payload},
        source="posts",
        example_post_ids=(),
        created_at=NOW,
    )


def framework(i: int, title: str, description: str):
    from lumi_ai.ports import FrameworkOut

    return FrameworkOut(
        id=i,
        profile_id=1,
        report_id=1,
        name=f"fw{i}",
        title=title,
        description=description,
        evidence_post_refs=(),
        lift=2.0,
        confidence=0.8,
        payload={"key": f"fw{i}"},
    )


def report(status="ok", frameworks=()):
    from lumi_ai.ports import NicheReportOut
    from lumi_ai.tests.fakes import NOW

    return NicheReportOut(
        id=1,
        profile_id=1,
        niche_key="saas",
        status=status,
        posts_analyzed=10,
        winner_count=3,
        payload={},
        frameworks=tuple(frameworks),
        detail=None,
        created_at=NOW,
    )
