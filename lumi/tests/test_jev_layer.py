"""Tests for the Jev decision layer: shared client helpers and decision gates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from typesafe_sdk import TypeSafeError

from app.agent import loop
from app.services import enforcement, jev, repurpose
from app.services.enforcement import (
    EnforcementResult,
    judge_caption,
    needs_retry,
    retry_feedback,
)
from app.tools import advice

# --- jev shared client helpers -------------------------------------------------


async def test_ask_noul_returns_scores(monkeypatch):
    fake = SimpleNamespace(
        system_one=AsyncMock(
            return_value=SimpleNamespace(answers={"q": SimpleNamespace(noul=0.69)})
        )
    )
    monkeypatch.setattr(jev, "_client", lambda: fake)
    assert await jev.ask_noul({"a": 1}, {"q": "instructions"}) == {"q": 0.69}


async def test_ask_returns_none_on_typesafe_error(monkeypatch):
    fake = SimpleNamespace(system_one=AsyncMock(side_effect=TypeSafeError("down")))
    monkeypatch.setattr(jev, "_client", lambda: fake)
    assert await jev.ask_noul({}, {"q": "i"}) is None


async def test_ask_returns_none_on_unexpected_error(monkeypatch):
    fake = SimpleNamespace(system_one=AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(jev, "_client", lambda: fake)
    assert await jev.ask({}, {"q": object()}) is None


async def test_ask_choice_returns_label(monkeypatch):
    fake = SimpleNamespace(
        system_one=AsyncMock(
            return_value=SimpleNamespace(
                answers={"difficulty": SimpleNamespace(choice="easy")}
            )
        )
    )
    monkeypatch.setattr(jev, "_client", lambda: fake)
    label = await jev.ask_choice(
        state={}, name="difficulty", instructions="i", criteria={"easy": "e"}
    )
    assert label == "easy"


# --- repurpose confidence retry decision --------------------------------------


def test_retry_on_must_keep_failure():
    result = EnforcementResult(must_keep_passed=False, feedback="missing phrase(s): v2.0")
    assert needs_retry(result) is True
    assert "missing phrase(s)" in retry_feedback(result)


def test_retry_on_low_judge_confidence():
    result = EnforcementResult(
        must_keep_passed=True, judge_verdict="no", judge_confidence=0.4
    )
    assert needs_retry(result) is True
    assert "semantic judge" in retry_feedback(result)


def test_retry_when_confidence_below_threshold_only():
    result = EnforcementResult(
        must_keep_passed=True, judge_verdict="yes", judge_confidence=0.6
    )
    assert needs_retry(result) is True


def test_no_retry_when_judge_confident():
    result = EnforcementResult(
        must_keep_passed=True, judge_verdict="yes", judge_confidence=0.9
    )
    assert needs_retry(result) is False
    assert retry_feedback(result) == ""


def test_no_retry_when_judge_skipped():
    result = EnforcementResult(must_keep_passed=True, judge_verdict=None)
    assert needs_retry(result) is False


async def test_generate_platform_repurpose_appends_revision_feedback(monkeypatch):
    captured = {}

    async def fake_completion(messages, tools, model=None):
        captured["messages"] = messages
        content = '{"platform": "x", "adapted_text": "rewritten", "changes": []}'
        completion = SimpleNamespace(
            model=model, choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        return completion, "groq"

    monkeypatch.setattr(repurpose, "chat_completion_with_provider", fake_completion)

    await repurpose.generate_platform_repurpose(
        "original", platform="x", revision_feedback="preserve the meaning"
    )

    user_prompt = captured["messages"][1]["content"]
    assert "Revision required" in user_prompt
    assert "preserve the meaning" in user_prompt


async def test_judge_caption_falls_back_when_jev_broken(monkeypatch):
    async def broken_jev(original, rewrite):
        raise RuntimeError("jev exploded")

    async def fake_fallback(original, rewrite):
        return "yes", 0.91

    monkeypatch.setattr(enforcement, "_judge_jev", broken_jev)
    monkeypatch.setattr(enforcement, "_judge_llm_fallback", fake_fallback)

    verdict, confidence, source = await judge_caption("orig", "rewrite")
    assert (verdict, confidence, source) == ("yes", 0.91, "llm_fallback")


# --- loop early-exit sufficiency gate -----------------------------------------


async def test_enough_information_true_when_jev_agrees(monkeypatch):
    async def fake_noul(state, questions):
        return {"sufficient": 0.8}

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    messages = [{"role": "tool", "content": '{"found": "data"}'}]
    assert await loop._enough_information("what works?", messages) is True


async def test_enough_information_false_when_jev_low(monkeypatch):
    async def fake_noul(state, questions):
        return {"sufficient": 0.3}

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    messages = [{"role": "tool", "content": '{"found": "data"}'}]
    assert await loop._enough_information("what works?", messages) is False


async def test_enough_information_false_when_jev_down(monkeypatch):
    async def fake_noul(state, questions):
        return None

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    messages = [{"role": "tool", "content": "data"}]
    assert await loop._enough_information("q", messages) is False


async def test_enough_information_skips_jev_without_tool_results(monkeypatch):
    called = False

    async def fake_noul(state, questions):
        nonlocal called
        called = True
        return {"sufficient": 1.0}

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    assert await loop._enough_information("q", [{"role": "user", "content": "hi"}]) is False
    assert called is False


# --- memory extraction gate ----------------------------------------------------


async def test_memory_gate_skips_transient_turn(monkeypatch):
    extracted = []

    async def fake_extract(profile_id, user_message, reply, handle=""):
        extracted.append(profile_id)

    async def fake_noul(state, questions):
        return {"durable": 0.1}

    monkeypatch.setattr(loop, "extract_turn_memories", fake_extract)
    monkeypatch.setattr(jev, "ask_noul", fake_noul)

    await loop._gated_memory_extraction(7, "what time is it", "it is 3pm")
    assert extracted == []


async def test_memory_gate_extracts_durable_turn(monkeypatch):
    extracted = []

    async def fake_extract(profile_id, user_message, reply, handle=""):
        extracted.append(profile_id)

    async def fake_noul(state, questions):
        return {"durable": 0.9}

    monkeypatch.setattr(loop, "extract_turn_memories", fake_extract)
    monkeypatch.setattr(jev, "ask_noul", fake_noul)

    await loop._gated_memory_extraction(7, "I always post at 9am", "noted")
    assert extracted == [7]


async def test_memory_gate_fails_open_when_jev_down(monkeypatch):
    extracted = []

    async def fake_extract(profile_id, user_message, reply, handle=""):
        extracted.append(profile_id)

    async def fake_noul(state, questions):
        return None

    monkeypatch.setattr(loop, "extract_turn_memories", fake_extract)
    monkeypatch.setattr(jev, "ask_noul", fake_noul)

    await loop._gated_memory_extraction(7, "msg", "reply")
    assert extracted == [7]


# --- advice relevance filter ---------------------------------------------------


def _fw(i):
    return {"id": f"fw{i}", "text": f"framework {i}"}


def _post(i):
    return {"id": f"p{i}", "text": f"post {i}"}


async def test_relevance_filter_drops_low_scores(monkeypatch):
    async def fake_noul(state, questions):
        return {"framework_0": 0.9, "post_0": 0.2}

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    fw, posts = await advice._relevance_filter("launch hooks", [_fw(0)], [_post(0)])
    assert fw == [_fw(0)]
    assert posts == []


async def test_relevance_filter_fails_open_when_jev_down(monkeypatch):
    async def fake_noul(state, questions):
        return None

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    fw, posts = await advice._relevance_filter("hooks", [_fw(0), _fw(1)], [_post(0)])
    assert fw == [_fw(0), _fw(1)]
    assert posts == [_post(0)]


async def test_relevance_filter_caps_candidates(monkeypatch):
    async def fake_noul(state, questions):
        return {name: 1.0 for name in questions}

    monkeypatch.setattr(jev, "ask_noul", fake_noul)
    fws = [_fw(i) for i in range(6)]
    posts = [_post(i) for i in range(6)]
    kept_fw, kept_posts = await advice._relevance_filter("q", fws, posts)
    assert len(kept_fw) == advice.RELEVANCE_FILTER_CAP
    assert len(kept_posts) == advice.RELEVANCE_FILTER_CAP
