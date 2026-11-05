import pytest

from lumi_ai.config import AIConfig
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.enforcement import EnforcementReviewer
from lumi_ai.generation.flow import GenerationService
from lumi_ai.generation.tools import MAX_SOURCE_CHARS, build, normalize_phrases
from lumi_ai.tests.agent.harness import say
from lumi_ai.tests.fakes import FakePosts, FakeRepurpose, FakeVoice, make_post
from lumi_ai.tests.generation.support import FakeJudge, TierLLM, reply
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolContext

REASON = "the user asked to write this post"
SRC = "We shipped the new dashboard today. See https://acme.io/new @acme"
GOOD = "Our new dashboard is live. https://acme.io/new @acme"


def make(script, judge=None, posts=None):
    llm = TierLLM(script)
    store = FakeRepurpose()
    judge = judge or FakeJudge()
    service = GenerationService(
        llm, ContextBuilder(FakeVoice()), EnforcementReviewer(judge), store, judge=judge
    )
    registry = build_registry(
        ToolDeps(profiles=None, repurpose=store), extra=build(service, posts)
    )
    return registry, store, llm


def ctx() -> ToolContext:
    return ToolContext(profile_id=1, config=AIConfig())


def test_both_tools_are_registered_through_extra_and_never_cached() -> None:
    registry, *_ = make([])
    assert {"generate_post", "repurpose_caption", "submit_action"} <= set(
        registry.names
    )
    for name in ("generate_post", "repurpose_caption"):
        spec = registry.get(name)
        assert (spec.cost, spec.side_effects, spec.cache_ttl) == ("llm", "writes_db", 0)


def test_phrases_accept_a_json_string_a_single_string_and_dedupe() -> None:
    assert normalize_phrases('["a", "b", "a"]') == ["a", "b"]
    assert normalize_phrases("just one") == ["just one"]
    assert normalize_phrases(["x", " ", "y"]) == ["x", "y"]
    assert normalize_phrases(None) == []


@pytest.mark.asyncio
async def test_repurpose_returns_the_chosen_draft_with_its_evidence() -> None:
    judge = FakeJudge(choice=["easy"], noul=[{"preserves_meaning": 0.9}])
    registry, store, _ = make(
        [reply(GOOD, [{"change": "shorter", "reason": "x"}])], judge
    )
    out = await registry.call(
        ctx(),
        "repurpose_caption",
        {"reason": REASON, "platform": "linkedin", "source_text": SRC},
    )
    assert out["text"] == GOOD and out["platform"] == "linkedin"
    assert out["attempt_id"] in store.known and out["request_id"] == 1
    assert out["judge"] == {"verdict": "yes", "confidence": 0.9}
    assert out["must_keep_passed"] and not out["needs_review"]
    assert out["characters"] == len(GOOD) and out["limit"] == 3000
    assert out["context_used"]["voice"] == "none" and out["context_used"]["warnings"]
    assert out["model"] == "fake-model" and out["fallback_model_used"] is False
    assert store.requests[0]["source_post_id"] is None


@pytest.mark.asyncio
async def test_no_judge_is_reported_as_needs_review() -> None:
    registry, *_ = make([reply(GOOD)])
    out = await registry.call(
        ctx(),
        "repurpose_caption",
        {"reason": REASON, "platform": "linkedin", "source_text": SRC},
    )
    assert out["judge"] is None and out["needs_review"]
    assert any("judge unavailable" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_repurposing_a_stored_post_links_it_and_checks_ownership() -> None:
    posts = FakePosts(
        [make_post(5, SRC, platform="x"), make_post(6, "theirs", profile_id=2)]
    )
    judge = FakeJudge(noul=[{"preserves_meaning": 0.9}])
    registry, store, _ = make([reply(GOOD)], judge, posts)
    out = await registry.call(
        ctx(),
        "repurpose_caption",
        {"reason": REASON, "platform": "linkedin", "post_id": 5},
    )
    assert out["text"] == GOOD and store.requests[0]["source_post_id"] == 5
    other = await registry.call(
        ctx(),
        "repurpose_caption",
        {"reason": REASON, "platform": "linkedin", "post_id": 6},
    )
    assert "no post with id 6" in other["error"]


@pytest.mark.asyncio
async def test_generate_post_in_topic_mode() -> None:
    registry, store, _ = make([reply("Pricing is a product decision.")])
    out = await registry.call(
        ctx(),
        "generate_post",
        {
            "reason": REASON,
            "platform": "x",
            "topic": "pricing",
            "goal": "get replies",
            "must_keep_phrases": '["pricing"]',
        },
    )
    assert (
        out["text"] == "Pricing is a product decision." and out["route"] == "standard"
    )
    assert (
        store.requests[0]["mode"] == "topic"
        and "goal: get replies" in store.requests[0]["brief"]
    )
    assert (
        out["judge"] is None and not out["needs_review"]
    )  # no source, so no meaning judge to be missing


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args", "message"),
    [
        ("generate_post", {"platform": "myspace", "topic": "t"}, "unknown platform"),
        ("generate_post", {"platform": "x", "topic": "  "}, "topic is required"),
        ("repurpose_caption", {"platform": "x"}, "nothing to rewrite"),
        (
            "repurpose_caption",
            {"platform": "x", "source_text": "a" * (MAX_SOURCE_CHARS + 1)},
            "longer than",
        ),
        ("repurpose_caption", {"platform": "x", "post_id": 3}, "not available"),
        (
            "generate_post",
            {
                "platform": "x",
                "topic": "t",
                "must_keep_phrases": [str(i) for i in range(11)],
            },
            "at most",
        ),
    ],
)
async def test_bad_input_is_an_error_and_never_reaches_the_model(
    tool, args, message
) -> None:
    registry, store, llm = make([])
    out = await registry.call(ctx(), tool, {"reason": REASON, **args})
    assert message in out["error"]
    assert llm.tiers == [] and store.requests == []


@pytest.mark.asyncio
async def test_total_failure_says_nothing_was_saved() -> None:
    registry, store, _ = make([say("no"), say("no"), say("no")])
    out = await registry.call(
        ctx(), "generate_post", {"reason": REASON, "platform": "x", "topic": "t"}
    )
    assert out["saved"] is False and "no usable draft" in out["error"]
    assert store.requests == []
