import pytest

from lumi_ai.generation.platforms import rules_for
from lumi_ai.generation.writer import (
    NO_VOICE,
    DraftUnusable,
    Revision,
    Writer,
    WriterContext,
    build_messages,
    format_voice,
    parse_draft,
)
from lumi_ai.tests.agent.harness import FakeLLM, say
from lumi_ai.tests.generation.support import brief, reply

CTX = WriterContext("Tone: plain")


def test_parse_accepts_fenced_json_with_changes() -> None:
    raw = '```json\n{"text": " Hello ", "changes": [{"change": "shorter", "reason": "limit"}, {"x": 1}]}\n```'
    text, changes = parse_draft(raw)
    assert text == "Hello"
    assert [(c.change, c.reason) for c in changes] == [("shorter", "limit")]


@pytest.mark.parametrize(
    "raw",
    ["just prose", "[1, 2]", '{"text": ""}', '{"text": 5}', '{"body": "x"}', ""],
)
def test_parse_rejects_anything_that_is_not_a_draft(raw: str) -> None:
    with pytest.raises(DraftUnusable):
        parse_draft(raw)


def test_prompt_states_the_platform_limit_voice_and_mandatory_phrases() -> None:
    b = brief(platform="x", must_keep=("Acme Cloud",))
    system, user = build_messages(b, rules_for("x"), WriterContext("Tone: plain"), None)
    assert "280 characters" in system["content"] and "Tone: plain" in system["content"]
    assert b.source_text in user["content"] and "Acme Cloud" in user["content"]
    assert "rejected" not in user["content"]


def test_prompt_for_a_revision_carries_the_previous_draft_and_the_note() -> None:
    _, user = build_messages(
        brief(), rules_for("linkedin"), CTX, Revision("old draft", "missing @acme")
    )
    assert "old draft" in user["content"] and "missing @acme" in user["content"]


def test_topic_prompt_uses_topic_goal_and_reference_but_no_source_caption() -> None:
    b = brief(
        mode="topic",
        topic="pricing",
        goal="get demos",
        source_text="the old price was 9",
    )
    _, user = build_messages(b, rules_for("linkedin"), CTX, None)
    text = user["content"]
    assert "about:\npricing" in text and "get demos" in text and "old price" in text
    assert "Source caption to adapt" not in text


def test_voice_formatting_never_invents_a_voice() -> None:
    assert format_voice(None) == NO_VOICE and format_voice({}) == NO_VOICE
    text = format_voice({"tone": "dry", "representative_excerpts": ["a", "b"]})
    assert "Tone: dry" in text and '["a", "b"]' in text


@pytest.mark.asyncio
async def test_write_returns_the_drafts_provenance() -> None:
    llm = FakeLLM([reply("Out now.", [{"change": "tightened", "reason": "x limit"}])])
    draft = await Writer(llm).write(brief(), rules_for("linkedin"), CTX, tier="small")
    assert (draft.text, draft.tier, draft.provider, draft.model) == (
        "Out now.",
        "small",
        "fake",
        "fake-model",
    )
    assert not draft.is_fallback and draft.changes[0].change == "tightened"


@pytest.mark.asyncio
async def test_an_unusable_reply_raises_instead_of_returning_the_source() -> None:
    llm = FakeLLM([say("Sure! Here is your post: Out now.")])
    with pytest.raises(DraftUnusable):
        await Writer(llm).write(brief(), rules_for("linkedin"), CTX, tier="large")
