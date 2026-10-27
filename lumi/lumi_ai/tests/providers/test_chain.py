"""Chain behaviour. The first block mirrors the legacy ``tests/test_provider_fallback.py``."""

import pytest

from lumi_ai.config import AIConfig
from lumi_ai.providers import (
    AllProvidersFailed,
    LLMChain,
    NoProviderConfigured,
    ProviderSpec,
    RequestTooLarge,
    UsageRecord,
)

from ._fakes import Clock, FakeCreate, api_error, fake_client

MSG = [{"role": "user", "content": "hi"}]
GROQ_MODELS = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b")
OR_MODELS = ("meta-llama/llama-3.3-70b-instruct",)


def make_chain(specs, *, clock=None, sink=None, config=None):
    """specs: (name, models, script[, extra kwargs]) -> (chain, {name: FakeCreate})."""
    creates, providers = {}, []
    for name, models, script, *rest in specs:
        create = FakeCreate(script)
        creates[name] = create
        providers.append(
            ProviderSpec(
                name=name,
                client=fake_client(create),
                models=tuple(models),
                **(rest[0] if rest else {}),
            )
        )
    chain = LLMChain(
        providers, config or AIConfig(), usage_sink=sink, clock=clock or Clock()
    )
    return chain, creates


async def test_groq_413_falls_back_to_second_model():
    chain, c = make_chain([("groq", GROQ_MODELS, [api_error(413), "ok"])])
    result = await chain.complete(MSG, [])
    assert (result.provider, result.model) == ("groq", "qwen/qwen3.8-27b")
    assert c["groq"].models == list(GROQ_MODELS)


async def test_second_model_failure_moves_to_next_provider():
    chain, _ = make_chain(
        [
            ("groq", GROQ_MODELS, [api_error(413), api_error(429)]),
            ("openrouter", OR_MODELS, ["ok"]),
        ]
    )
    result = await chain.complete(MSG, [])
    assert (result.provider, result.model) == ("openrouter", OR_MODELS[0])
    assert [a.kind for a in result.attempts] == ["too_large", "rate_limit"]


async def test_single_model_provider_moves_on_after_one_error():
    chain, c = make_chain(
        [
            ("openlux", ("qwen3.8-27b",), [api_error(401)]),
            ("groq", GROQ_MODELS, ["ok"]),
        ]
    )
    result = await chain.complete(MSG, [])
    assert result.provider == "groq"
    assert c["openlux"].models == ["qwen3.8-27b"]
    assert c["groq"].models == [GROQ_MODELS[0]]


async def test_explicit_model_pins_a_single_candidate():
    chain, c = make_chain(
        [("groq", ("openai/gpt-oss-20b", "openai/gpt-oss-120b"), [api_error(500)])]
    )
    with pytest.raises(AllProvidersFailed):
        await chain.complete(MSG, [], model="openai/gpt-oss-20b")
    assert c["groq"].models == ["openai/gpt-oss-20b"]


async def test_tier_pins_the_configured_tier_model_and_skips_providers_that_cannot_take_it():
    chain, c = make_chain(
        [
            ("openlux", ("qwen3.8-27b",), [], {"accepts_pinned_model": False}),
            ("groq", GROQ_MODELS, ["ok"]),
        ]
    )
    result = await chain.complete(MSG, [], tier="small")
    assert result.model == AIConfig().groq_model_small
    assert c["openlux"].models == []


async def test_all_providers_fail_carries_attempts_and_cause():
    chain, _ = make_chain(
        [
            ("groq", GROQ_MODELS, [api_error(413), api_error(429)]),
            ("openrouter", OR_MODELS, [api_error(402)]),
        ]
    )
    with pytest.raises(AllProvidersFailed, match="all LLM providers failed") as info:
        await chain.complete(MSG, [])
    assert [a.kind for a in info.value.attempts] == [
        "too_large",
        "rate_limit",
        "payment",
    ]
    assert info.value.last_status == 402
    assert info.value.__cause__ is not None
    assert isinstance(info.value, RuntimeError)


async def test_effort_400_retries_same_model_without_reasoning_effort():
    chain, c = make_chain([("groq", GROQ_MODELS[:1], [api_error(400), "ok"])])
    result = await chain.complete(MSG, [], effort="low")
    assert result.provider == "groq"
    assert c["groq"].models == [GROQ_MODELS[0]] * 2
    assert c["groq"].efforts == ["low", None]


async def test_effort_non_400_does_not_retry_same_model():
    chain, c = make_chain(
        [
            ("groq", GROQ_MODELS[:1], [api_error(401)]),
            ("openrouter", OR_MODELS, ["ok"]),
        ]
    )
    result = await chain.complete(MSG, [], effort="low")
    assert result.provider == "openrouter"
    assert c["groq"].efforts == ["low"]


async def test_no_effort_sends_no_reasoning_effort():
    chain, c = make_chain([("groq", GROQ_MODELS[:1], ["ok"])])
    await chain.complete(MSG, [])
    assert c["groq"].efforts == [None]


# ---- new behaviour -------------------------------------------------------------------------


@pytest.mark.parametrize("status", [402, 429])
async def test_cooldown_skips_a_failed_candidate_on_the_next_turn(status):
    clock = Clock()
    chain, c = make_chain(
        [
            ("groq", GROQ_MODELS[:1], [api_error(500), "ok", "ok"]),
            ("openrouter", OR_MODELS, [api_error(status), "ok", "ok"]),
        ],
        clock=clock,
    )
    # turn 1: groq 500 (no cooldown), openrouter fails with `status` -> everything failed
    with pytest.raises(AllProvidersFailed):
        await chain.complete(MSG, [])
    assert chain.is_resting("openrouter", OR_MODELS[0])
    assert not chain.is_resting("groq", GROQ_MODELS[0])
    # turn 2: groq answers; openrouter is not touched
    await chain.complete(MSG, [])
    assert c["openrouter"].models == [OR_MODELS[0]]


async def test_cooldown_expires():
    clock = Clock()
    chain, c = make_chain(
        [
            ("groq", GROQ_MODELS[:1], [api_error(429), api_error(429), "ok"]),
            ("openrouter", OR_MODELS, ["ok", "ok"]),
        ],
        clock=clock,
        config=AIConfig(provider_cooldown_seconds=60),
    )
    await chain.complete(MSG, [])  # groq 429 -> openrouter answers
    assert chain.is_resting("groq", GROQ_MODELS[0])
    await chain.complete(MSG, [])  # groq skipped
    assert len(c["groq"].models) == 1
    clock.t += 61
    assert not chain.is_resting("groq", GROQ_MODELS[0])
    result = await chain.complete(
        MSG, []
    )  # groq tried again (second 429), openrouter answers
    assert len(c["groq"].models) == 2 and result.provider == "openrouter"


async def test_retry_after_header_sets_cooldown_capped():
    clock = Clock()
    chain, _ = make_chain(
        [
            ("groq", GROQ_MODELS[:1], [api_error(429, {"retry-after": "5000"})]),
            ("openrouter", OR_MODELS, ["ok"]),
        ],
        clock=clock,
        config=AIConfig(provider_cooldown_max_seconds=900),
    )
    await chain.complete(MSG, [])
    clock.t += 899
    assert chain.is_resting("groq", GROQ_MODELS[0])
    clock.t += 2
    assert not chain.is_resting("groq", GROQ_MODELS[0])


async def test_when_everything_rests_candidates_are_still_tried():
    clock = Clock()
    chain, _ = make_chain(
        [("groq", GROQ_MODELS[:1], [api_error(429), "ok"])], clock=clock
    )
    with pytest.raises(AllProvidersFailed):
        await chain.complete(MSG, [])
    result = await chain.complete(MSG, [])  # still resting, but it is the only option
    assert result.provider == "groq"
    assert [a.kind for a in result.attempts] == ["cooldown"]
    assert not chain.is_resting("groq", GROQ_MODELS[0])  # success clears the cooldown


async def test_400_does_not_start_a_cooldown():
    chain, _ = make_chain([("groq", GROQ_MODELS[:1], [api_error(400)])])
    with pytest.raises(AllProvidersFailed):
        await chain.complete(MSG, [])
    assert not chain.is_resting("groq", GROQ_MODELS[0])


async def test_token_wall_skips_without_a_call():
    big = [{"role": "user", "content": "x" * 40_000}]
    chain, c = make_chain(
        [
            ("groq", GROQ_MODELS, [], {"max_request_tokens": 6700}),
            ("openrouter", OR_MODELS, ["ok"]),
        ]
    )
    result = await chain.complete(big, [])
    assert result.provider == "openrouter"
    assert c["groq"].models == []
    assert [a.kind for a in result.attempts] == ["too_large", "too_large"]


async def test_request_too_large_when_every_candidate_is_walled():
    big = [{"role": "user", "content": "x" * 40_000}]
    chain, _ = make_chain([("groq", GROQ_MODELS, [], {"max_request_tokens": 6700})])
    with pytest.raises(RequestTooLarge) as info:
        await chain.complete(big, [])
    assert info.value.estimated_tokens > 6700


async def test_empty_chain_raises_no_provider_configured():
    chain = LLMChain([], AIConfig())
    with pytest.raises(NoProviderConfigured):
        await chain.complete(MSG, [])


async def test_usage_is_reported_for_failures_and_successes_without_message_text():
    records: list[UsageRecord] = []
    chain, _ = make_chain(
        [("groq", GROQ_MODELS, [api_error(429), "ok"])], sink=records.append
    )
    await chain.complete([{"role": "user", "content": "secret text"}], [])
    assert [(r.ok, r.failure_kind, r.status_code) for r in records] == [
        (False, "rate_limit", 429),
        (True, None, None),
    ]
    assert records[1].total_tokens == 15 and records[1].tier is None
    await chain.complete(MSG, [], tier="large")
    assert records[-1].tier == "large"
    assert "secret" not in repr(records)


async def test_a_broken_usage_sink_does_not_break_the_call():
    def boom(_: UsageRecord) -> None:
        raise RuntimeError("db down")

    chain, _ = make_chain([("groq", GROQ_MODELS[:1], ["ok"])], sink=boom)
    assert (await chain.complete(MSG, [])).provider == "groq"
