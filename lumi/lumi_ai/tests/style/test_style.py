from __future__ import annotations

import json
from dataclasses import replace

import pytest

from lumi_ai.config import AIConfig
from lumi_ai.ports import ActivityOut, StyleAnswerIn
from lumi_ai.style import StyleService, VoiceExtractionError
from lumi_ai.style import tools as style_tools
from lumi_ai.style.extract import extract_voice, voice_from_answers
from lumi_ai.style.schema import measure, verbatim_excerpts
from lumi_ai.style.service import authentic_originals, spread_sample
from lumi_ai.tests.agent.harness import FakeLLM, say
from lumi_ai.tests.fakes import NOW, FakePosts, FakeVoice, make_post
from lumi_ai.tools.registry import ToolContext

pytestmark = pytest.mark.asyncio

CAPTIONS = [
    "Building in public is hard. But shipping daily changes everything.",
    "Stop overthinking your stack. Just deploy it.",
    "What is the biggest blocker in your agent loop?",
    "3 tips for cleaner code:\n- Keep functions small\n- Test early",
    "Never wait for perfection. Real feedback comes after launch.",
]

GOOD = {
    "archetype_name": "The Pragmatic Builder",
    "creator_bio_summary": "A founder who ships.",
    "perspective": "second person",
    "tone": "blunt, practical",
    "emoji_use": "never uses emojis",
    "hook_style": "short imperative",
    "vocabulary": "developer jargon",
    "structure": "one-liners",
    "call_to_action_style": "none",
    "target_length_words": "8-20 words",
    "things_they_never_do": ["use hashtags", "ask for likes"],
    "reply_style": "terse and friendly",
    "representative_excerpts": [
        "Stop overthinking your stack. Just deploy it.",
        "a paraphrase that is not in any post",
    ],
}


def reply(data: dict | str) -> dict:
    return say(data if isinstance(data, str) else json.dumps(data))


def posts(n: int = 6, **kw):
    return [
        make_post(
            i, CAPTIONS[i % 5] + (f" #{i}" if i >= 5 else ""), days_ago=i + 1, **kw
        )
        for i in range(1, n + 1)
    ]


def service(script, post_rows, *, voice=None, activity=None, config=None):
    llm = FakeLLM(script)
    store = voice or FakeVoice()
    svc = StyleService(llm, FakePosts(post_rows, activity), store, config or AIConfig())
    return svc, llm, store


# --- schema and measures ------------------------------------------------------------


async def test_measure_counts_what_is_in_the_posts():
    m = measure(["hi 🔥 #a", "https://x.co/a @bob?", "plain\ntext"])
    assert m["posts"] == 3
    assert m["emoji_per_post"] == 0.33
    assert m["share_with_hashtag"] == 0.33 and m["share_with_link"] == 0.33
    assert m["share_with_mention"] == 0.33 and m["share_with_question"] == 0.33
    assert m["share_multiline"] == 0.33
    assert measure([]) == {"posts": 0}


async def test_excerpts_must_occur_in_a_post():
    kept = verbatim_excerpts(
        ["Stop  overthinking your STACK.", "invented line"], CAPTIONS
    )
    assert kept == ["Stop  overthinking your STACK."]


async def test_authentic_originals_drops_replies_retweets_and_cut_text():
    rows = [
        make_post(1, "my own words"),
        make_post(2, "RT @x: not mine"),
        make_post(3, "@bob thanks!"),
        make_post(4, "a reply", kind="reply"),
        replace(make_post(5, "cut off…"), text_truncated=True),
        make_post(6, "   "),
        replace(make_post(7, "gone"), is_deleted_suspect=True),
        make_post(8, "a quote", kind="quote"),
    ]
    assert [p.id for p in authentic_originals(rows)] == [1, 8]


async def test_spread_sample_covers_the_whole_history_oldest_first():
    rows = [make_post(i, f"p{i}", days_ago=i) for i in range(1, 41)]
    sample = spread_sample(rows, 10)
    assert len(sample) == 10
    assert sample == sorted(sample, key=lambda p: p.published_at)
    assert sample[0].id == 40 and sample[-1].id <= 5  # oldest ... near newest


# --- extraction ---------------------------------------------------------------------


async def test_extract_validates_joins_lists_and_keeps_only_real_quotes():
    llm = FakeLLM([reply(GOOD)])
    out = await extract_voice(llm, CAPTIONS, replies=["lol yes"], platform="x")
    assert out["things_they_never_do"] == "use hashtags; ask for likes"
    assert out["representative_excerpts"] == [
        "Stop overthinking your stack. Just deploy it."
    ]
    assert out["posts_analyzed_count"] == 5
    assert out["measured"]["posts"] == 5
    assert out["extraction"]["prompt_version"] == "voice-v2"
    assert out["reply_style"] == "terse and friendly"
    prompt = llm.seen[0][1]["content"]
    assert "REPLY SAMPLES" in prompt and "on x" in prompt


async def test_no_replies_means_no_reply_style_even_if_the_model_invents_one():
    out = await extract_voice(FakeLLM([reply(GOOD)]), CAPTIONS)
    assert out["reply_style"] == ""


async def test_fenced_json_with_prose_is_accepted():
    text = "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```\nHope it helps."
    out = await extract_voice(FakeLLM([reply(text)]), CAPTIONS)
    assert out["tone"] == "blunt, practical"


async def test_one_repair_round_then_success():
    broken = dict(GOOD)
    del broken["tone"]
    llm = FakeLLM([reply(broken), reply(GOOD)])
    out = await extract_voice(llm, CAPTIONS)
    assert out["tone"] == "blunt, practical"
    repair = llm.seen[1][-1]["content"]
    assert "rejected" in repair and "tone" in repair


async def test_two_bad_replies_raise_and_never_invent_a_profile():
    llm = FakeLLM([reply("not json"), reply("still not json")])
    with pytest.raises(VoiceExtractionError):
        await extract_voice(llm, CAPTIONS)
    assert len(llm.seen) == 2


async def test_prior_profile_rides_the_prompt_for_continuity():
    llm = FakeLLM([reply(GOOD)])
    await extract_voice(
        llm, CAPTIONS, prior={"tone": "punchy", "emoji_use": ""}, prior_version=3
    )
    prompt = llm.seen[0][1]["content"]
    assert "Version: 3" in prompt and "tone: punchy" in prompt
    assert "emoji_use" not in prompt.split("PRIOR VOICE PROFILE")[1]


async def test_voice_from_answers_marks_source_and_keeps_only_pasted_excerpts():
    data = dict(GOOD, representative_excerpts=["Ship it.", "made up"])
    out = await voice_from_answers(
        FakeLLM([reply(data)]), {"tone": "blunt", "example": "Ship it. Always."}
    )
    assert out["extraction"]["source"] == "questions"
    assert out["representative_excerpts"] == ["Ship it."]
    assert out["posts_analyzed_count"] == 0
    with pytest.raises(VoiceExtractionError):
        await voice_from_answers(FakeLLM([]), {"tone": "  "})


# --- the service --------------------------------------------------------------------


async def test_refresh_below_the_minimum_asks_for_questions_and_stores_nothing():
    svc, llm, store = service([], posts(4))
    result = await svc.refresh_voice(1)
    assert result.status == "needs_style_questions" and result.posts_found == 4
    assert llm.seen == [] and store.saved == []


async def test_refresh_saves_a_posts_voice_with_example_ids_and_replies():
    activity = [
        ActivityOut(1, 1, "x", "reply", "yep, agreed", NOW),
        ActivityOut(2, 1, "x", "retweet", "RT @a: boo", NOW),
    ]
    svc, llm, store = service([reply(GOOD)], posts(6), activity=activity)
    result = await svc.refresh_voice(1)
    assert result.status == "created"
    saved = store.saved[0]
    assert saved.source == "posts" and saved.platform is None
    assert store.columns == [
        ("fake-model", "voice-v2")
    ]  # the model and prompt_version columns
    assert set(saved.example_post_ids) == {1, 2, 3, 4, 5, 6}
    prompt = llm.seen[0][1]["content"]
    assert (
        "yep, agreed" in prompt and "boo" not in prompt
    )  # retweets never teach the voice


async def test_second_refresh_sends_the_prior_voice():
    svc, llm, store = service([reply(GOOD), reply(GOOD)], posts(6))
    await svc.refresh_voice(1)
    await svc.refresh_voice(1)
    assert "PRIOR VOICE PROFILE" in llm.seen[1][1]["content"]
    assert [v.version for v in store.saved] == [1, 2]


async def test_platform_voice_uses_only_that_platforms_posts():
    rows = posts(6, platform="linkedin") + [make_post(50, "an x post", platform="x")]
    svc, llm, _store = service([reply(GOOD)], rows)
    result = await svc.refresh_voice(1, "linkedin")
    assert result.voice.platform == "linkedin"
    assert "an x post" not in llm.seen[0][1]["content"]
    assert (await svc.refresh_voice(1, "x")).status == "needs_style_questions"


async def test_extraction_failure_is_reported_and_nothing_is_saved():
    svc, _, store = service([reply("nope"), reply("nope")], posts(6))
    result = await svc.refresh_voice(1)
    assert result.status == "failed" and "no usable voice profile" in result.reason
    assert store.saved == []


async def test_cold_start_builds_from_answers_then_posts_replace_it():
    voice = FakeVoice()
    voice.answers = [
        StyleAnswerIn("tone", "blunt"),
        StyleAnswerIn("never", "buzzwords"),
    ]
    svc, _, store = service([reply(GOOD)], [], voice=voice)
    cold = await svc.ensure_voice(1)
    assert cold.status == "created" and store.saved[0].source == "questions"

    svc2 = StyleService(FakeLLM([reply(GOOD)]), FakePosts(posts(6)), voice, AIConfig())
    warm = await svc2.ensure_voice(1)
    assert warm.voice.source == "posts" and warm.voice.version == 2
    # answers never overwrite a voice learned from real posts
    again = await svc2.build_from_answers(1)
    assert again.status == "kept" and again.voice.source == "posts"


async def test_ensure_voice_with_nothing_asks_for_questions():
    svc, llm, _store = service([], posts(2))
    result = await svc.ensure_voice(1)
    assert (
        result.status == "needs_style_questions"
        and "only 2 usable posts" in result.reason
    )
    assert llm.seen == []


# --- the tool -----------------------------------------------------------------------


async def test_extract_voice_profile_tool_shapes():
    svc, _, _store = service([reply(GOOD)], posts(6))
    (spec,) = style_tools.build(svc)
    assert spec.cost == "llm" and spec.name == "extract_voice_profile"
    out = await spec.handler(ToolContext(profile_id=1))
    assert out["needs_style_questions"] is False and out["version"] == 1
    assert out["payload"]["tone"] == "blunt, practical"

    thin, _, _ = service([], posts(1))
    (spec,) = style_tools.build(thin)
    out = await spec.handler(ToolContext(profile_id=1))
    assert out["needs_style_questions"] is True
    assert {q["question_key"] for q in out["questions"]} >= {"tone", "never", "example"}

    bad, _, _ = service([reply("x"), reply("y")], posts(6))
    (spec,) = style_tools.build(bad)
    assert "error" in await spec.handler(ToolContext(profile_id=1))
