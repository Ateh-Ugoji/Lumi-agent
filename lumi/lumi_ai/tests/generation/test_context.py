import pytest

from lumi_ai.config import AIConfig
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.tests.competitors.support import FakeReports
from lumi_ai.tests.fakes import FakeVoice, make_post
from lumi_ai.tests.generation.support import (
    StubRetriever,
    brief,
    framework,
    report,
    voice_out,
)
from lumi_ai.tests.rag.support import WordEmbedder


@pytest.mark.asyncio
async def test_without_any_voice_the_context_says_so() -> None:
    ctx, used = await ContextBuilder(FakeVoice()).build(brief(), AIConfig())
    assert used.voice == "none" and "No voice profile" in ctx.voice_text
    assert "extract_voice_profile" in used.warnings[0]


@pytest.mark.asyncio
async def test_platform_voice_beats_the_general_one_which_beats_nothing() -> None:
    voices = FakeVoice()
    voices.current = voice_out(None, 1, tone="general tone")
    _, used = await ContextBuilder(voices).build(brief(), AIConfig())
    assert (used.voice, used.voice_version) == ("general", 1)
    voices.saved.append(voice_out("linkedin", 2, tone="li tone"))
    ctx, used = await ContextBuilder(voices).build(brief(), AIConfig())
    assert (used.voice, used.voice_version) == (
        "linkedin",
        2,
    ) and "li tone" in ctx.voice_text


@pytest.mark.asyncio
async def test_examples_come_from_the_platform_then_any_platform_and_are_clipped() -> (
    None
):
    long = "word " * 200
    retriever = StubRetriever(
        own=[], anywhere=[make_post(5, long), make_post(6, "short one")]
    )
    ctx, used = await ContextBuilder(FakeVoice(), retriever=retriever).build(
        brief(), AIConfig(generation_examples=2, generation_example_chars=50)
    )
    assert [c["platform"] for c in retriever.calls] == ["linkedin", None]
    assert used.example_post_ids == (5, 6)
    assert len(ctx.examples[0]) <= 50 and ctx.examples[0].endswith("…")


@pytest.mark.asyncio
async def test_a_retrieval_failure_is_a_warning_not_a_failed_generation() -> None:
    retriever = StubRetriever(error=RuntimeError("chroma down"))
    ctx, used = await ContextBuilder(FakeVoice(), retriever=retriever).build(
        brief(), AIConfig()
    )
    assert ctx.examples == () and any("chroma down" in w for w in used.warnings)


@pytest.mark.asyncio
async def test_topic_mode_gets_the_closest_frameworks_of_an_ok_report_only() -> None:
    reports = FakeReports()
    reports.reports.append(
        report(
            frameworks=[
                framework(1, "Pricing teardown", "pricing price cost value tiers"),
                framework(2, "Founder story", "origin story struggle lesson"),
                framework(3, "Hot take", "contrarian opinion claim"),
            ]
        )
    )
    builder = ContextBuilder(FakeVoice(), reports=reports, embedder=WordEmbedder())
    topic = brief(mode="topic", topic="pricing cost tiers", source_text=None)
    ctx, used = await builder.build(topic, AIConfig(generation_frameworks=1))
    assert used.frameworks == ("fw1",) and "Pricing teardown" in ctx.frameworks[0]
    # repurpose mode never adds structures: the source already is the structure
    _, used = await builder.build(brief(), AIConfig())
    assert used.frameworks == ()
    # a report that was not ok is not advice
    reports.reports.append(
        report(status="insufficient_data", frameworks=[framework(4, "x", "y")])
    )
    _, used = await builder.build(topic, AIConfig())
    assert used.frameworks == ()
