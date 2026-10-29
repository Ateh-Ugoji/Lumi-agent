import pytest

from lumi_ai.config import AIConfig
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.enforcement import UNAVAILABLE, EnforcementReviewer
from lumi_ai.generation.flow import GenerationFailed, GenerationService, best_attempt
from lumi_ai.generation.types import Review
from lumi_ai.tests.agent.harness import say
from lumi_ai.tests.fakes import FakeRepurpose, FakeVoice
from lumi_ai.tests.generation.support import (
    FakeJudge,
    TierLLM,
    brief,
    reply,
    voice_out,
)

SRC = "We shipped the new dashboard today. See https://acme.io/new @acme"
GOOD = "Our new dashboard is live. https://acme.io/new @acme"


def rig(script, judge=None, voice=None):
    llm = TierLLM(script)
    store = FakeRepurpose()
    voices = voice or FakeVoice()
    service = GenerationService(
        llm,
        ContextBuilder(voices),
        EnforcementReviewer(judge),
        store,
        judge=judge,
    )
    return service, llm, store


@pytest.mark.asyncio
async def test_a_good_first_draft_is_saved_once_with_its_provenance() -> None:
    judge = FakeJudge(choice=["easy"], noul=[{"preserves_meaning": 0.95}])
    service, llm, store = rig([reply(GOOD)], judge)
    result = await service.run(brief(source_text=SRC), AIConfig())
    assert len(llm.tiers) == 1 and llm.tiers == [
        "small"
    ]  # easy routes to the small model
    [req] = store.requests
    assert (req["source_text"], req["route_label"], req["mode"]) == (
        SRC,
        "easy",
        "repurpose",
    )
    [attempt] = req["attempts"]
    assert (
        attempt.output == GOOD and attempt.attempt_no == 1 and attempt.must_keep_passed
    )
    assert (attempt.tier, attempt.model, attempt.provider) == (
        "small",
        "fake-model",
        "fake",
    )
    assert (attempt.judge_verdict, attempt.judge_confidence) == ("yes", 0.95)
    assert result.attempt.id == result.saved[0].id and result.draft.text == GOOD


@pytest.mark.asyncio
async def test_regeneration_is_guided_by_the_failure_and_uses_the_large_tier() -> None:
    judge = FakeJudge(choice=["easy"], noul=[{"preserves_meaning": 0.9}])
    service, llm, store = rig([reply("Our dashboard is live."), reply(GOOD)], judge)
    result = await service.run(brief(source_text=SRC), AIConfig())
    assert llm.tiers == ["small", "large"]
    retry_prompt = llm.seen[1][-1]["content"]
    assert "Our dashboard is live." in retry_prompt and "lost link" in retry_prompt
    attempts = store.requests[0]["attempts"]
    assert [(a.attempt_no, a.must_keep_passed) for a in attempts] == [
        (1, False),
        (2, True),
    ]
    assert result.outcome.chosen == 1 and result.draft.text == GOOD


@pytest.mark.asyncio
async def test_must_keep_phrase_is_enforced_across_attempts() -> None:
    b = brief(
        mode="topic",
        platform="x",
        topic="launch",
        must_keep=("Acme Cloud",),
        source_text=None,
    )
    service, _, store = rig([reply("We launched."), reply("Acme Cloud is launched.")])
    result = await service.run(b, AIConfig())
    assert (
        result.draft.text == "Acme Cloud is launched."
        and result.review.must_keep_passed
    )
    assert (
        store.requests[0]["mode"] == "topic"
        and "topic: launch" in store.requests[0]["brief"]
    )
    assert store.requests[0]["route_label"] == "standard"


@pytest.mark.asyncio
async def test_unparseable_replies_are_retried_never_replaced_by_the_source() -> None:
    service, llm, store = rig(
        [say("prose, no json"), reply(GOOD)],
        FakeJudge(noul=[{"preserves_meaning": 0.9}]),
    )
    result = await service.run(brief(source_text=SRC), AIConfig())
    assert "unusable" in llm.seen[1][-1]["content"]
    [attempt] = store.requests[0]["attempts"]
    assert (
        attempt.attempt_no == 2 and attempt.output == GOOD
    )  # the failed try left no row
    assert result.draft.text == GOOD


@pytest.mark.asyncio
async def test_no_usable_draft_raises_and_saves_nothing() -> None:
    service, _, store = rig([say("no"), say("still no"), say("never")])
    with pytest.raises(GenerationFailed, match="3 attempt"):
        await service.run(brief(source_text=SRC), AIConfig())
    assert store.requests == []


@pytest.mark.asyncio
async def test_provider_errors_propagate_and_nothing_is_saved() -> None:
    service, _, store = rig(
        []
    )  # FakeLLM raises AssertionError when called with no script
    with pytest.raises(AssertionError):
        await service.run(brief(source_text=SRC), AIConfig())
    assert store.requests == []


@pytest.mark.asyncio
async def test_all_attempts_are_saved_and_the_best_one_is_chosen_not_the_last() -> None:
    judge = FakeJudge(
        choice=["standard"],
        noul=[
            {"preserves_meaning": 0.9},
            {"preserves_meaning": 0.2},
            {"preserves_meaning": 0.3},
        ],
    )
    service, _llm, store = rig([reply(GOOD)] * 3, judge)
    result = await service.run(brief(source_text=SRC), AIConfig())
    # first draft: yes 0.9 (>= 0.8, accepted) -> stops at once
    assert len(store.requests[0]["attempts"]) == 1 and result.outcome.chosen == 0

    judge = FakeJudge(
        choice=["standard"],
        noul=[
            {"preserves_meaning": 0.7},
            {"preserves_meaning": 0.2},
            {"preserves_meaning": 0.3},
        ],
    )
    service, _llm, store = rig([reply(GOOD)] * 3, judge)
    result = await service.run(brief(source_text=SRC), AIConfig())
    assert len(store.requests[0]["attempts"]) == 3  # 1 + 2 regenerations
    assert (
        result.outcome.chosen == 0 and result.attempt.attempt_no == 1
    )  # the 0.7 "yes" beats the "no"s


@pytest.mark.asyncio
async def test_regenerations_come_from_the_config() -> None:
    judge = FakeJudge(choice=["standard"], noul=[{"preserves_meaning": 0.1}] * 5)
    service, _llm, store = rig([reply(GOOD)] * 5, judge)
    await service.run(brief(source_text=SRC), AIConfig(generation_max_regenerations=0))
    assert len(store.requests[0]["attempts"]) == 1


@pytest.mark.asyncio
async def test_judge_unavailable_still_saves_with_no_verdict() -> None:
    service, _, store = rig([reply(GOOD)], FakeJudge())
    result = await service.run(brief(source_text=SRC), AIConfig())
    [attempt] = store.requests[0]["attempts"]
    assert attempt.judge_verdict is None and attempt.judge_confidence is None
    assert result.review.feedback == UNAVAILABLE


@pytest.mark.asyncio
async def test_the_voice_of_the_platform_reaches_the_prompt() -> None:
    voices = FakeVoice()
    voices.saved.append(voice_out("linkedin", tone="dry and exact"))
    service, llm, _ = rig(
        [reply(GOOD)], FakeJudge(noul=[{"preserves_meaning": 0.9}]), voices
    )
    result = await service.run(brief(source_text=SRC), AIConfig())
    assert "dry and exact" in llm.seen[0][0]["content"]
    assert (
        result.outcome.context.voice == "linkedin"
        and result.outcome.context.voice_version == 3
    )


def test_best_attempt_prefers_hard_pass_then_verdict_then_confidence_then_later() -> (
    None
):
    r = lambda **k: Review(**{"must_keep_passed": True, **k})
    reviews = [
        r(must_keep_passed=False, needs_retry=True),
        r(judge_verdict="no", judge_confidence=0.4, needs_retry=True),
        r(judge_verdict="yes", judge_confidence=0.7, needs_retry=True),
        r(judge_verdict="yes", judge_confidence=0.7, needs_retry=True),
    ]
    assert best_attempt(reviews) == 3
    assert best_attempt(reviews[:2]) == 1
