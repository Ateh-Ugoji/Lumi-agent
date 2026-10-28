"""Chain behaviour. The first block mirrors ``lumi/legacy/tests/test_provider_fallback.py``."""

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


def make_chain(specs, *, clock=None, sink=None, config=None, sleep=None):
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
    extra = {"sleep": sleep} if sleep is not None else {}
    chain = LLMChain(
        providers,
        config or AIConfig(),
        usage_sink=sink,
        clock=clock or Clock(),
        **extra,
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


async def test_all_413_raises_request_too_large_so_the_loop_can_trim():
    chain, _ = make_chain([("groq", GROQ_MODELS, [api_error(413), api_error(413)])])
    with pytest.raises(RequestTooLarge) as info:
        await chain.complete(MSG, [])
    assert isinstance(info.value, AllProvidersFailed)
    assert [a.kind for a in info.value.attempts] == ["too_large", "too_large"]


async def test_mixed_failures_are_not_request_too_large():
    chain, _ = make_chain([("groq", GROQ_MODELS, [api_error(413), api_error(500)])])
    with pytest.raises(AllProvidersFailed) as info:
        await chain.complete(MSG, [])
    assert not isinstance(info.value, RequestTooLarge)


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


class _Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


async def test_a_short_429_waits_and_retries_the_same_model():
    sleeps = _Sleeps()
    chain, c = make_chain(
        [
            (
                "groq",
                GROQ_MODELS,
                [api_error(429, {"x-ratelimit-reset-tokens": "1.5s"}), "ok"],
            )
        ],
        sleep=sleeps,
    )
    result = await chain.complete(MSG, [])
    assert (result.provider, result.model) == ("groq", GROQ_MODELS[0])
    assert c["groq"].models == [GROQ_MODELS[0], GROQ_MODELS[0]]
    assert sleeps.waits == [1.5]
    assert result.attempts == ()


async def test_retry_after_is_read_before_the_token_reset_header():
    sleeps = _Sleeps()
    chain, _ = make_chain(
        [
            (
                "groq",
                GROQ_MODELS,
                [
                    api_error(
                        429, {"retry-after": "3", "x-ratelimit-reset-tokens": "9s"}
                    ),
                    "ok",
                ],
            )
        ],
        sleep=sleeps,
    )
    await chain.complete(MSG, [])
    assert sleeps.waits == [3.0]


async def test_a_long_429_goes_to_the_next_model_without_waiting():
    sleeps = _Sleeps()
    chain, c = make_chain(
        [("groq", GROQ_MODELS, [api_error(429, {"retry-after": "5000"}), "ok"])],
        sleep=sleeps,
    )
    result = await chain.complete(MSG, [])
    assert result.model == GROQ_MODELS[1]
    assert c["groq"].models == list(GROQ_MODELS)
    assert sleeps.waits == []


async def test_a_429_without_a_wait_hint_does_not_wait():
    sleeps = _Sleeps()
    chain, c = make_chain([("groq", GROQ_MODELS, [api_error(429), "ok"])], sleep=sleeps)
    await chain.complete(MSG, [])
    assert c["groq"].models == list(GROQ_MODELS)
    assert sleeps.waits == []


async def test_the_wait_is_tried_once_then_the_next_model_answers():
    sleeps = _Sleeps()
    hint = {"retry-after": "2"}
    chain, c = make_chain(
        [("groq", GROQ_MODELS, [api_error(429, hint), api_error(429, hint), "ok"])],
        sleep=sleeps,
    )
    result = await chain.complete(MSG, [])
    assert result.model == GROQ_MODELS[1]
    assert c["groq"].models == [GROQ_MODELS[0], GROQ_MODELS[0], GROQ_MODELS[1]]
    assert sleeps.waits == [2.0]


def test_tool_calls_get_a_thought_signature_only_where_they_have_none():
    from lumi_ai.providers.chain import _with_tool_call_signature

    own = {"id": "b", "extra_content": {"google": {"thought_signature": "REAL"}}}
    foreign = {"id": "a", "type": "function"}
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [foreign, own]},
        {"role": "tool", "tool_call_id": "a", "content": "{}"},
    ]
    out = _with_tool_call_signature(history, "PLACEHOLDER")
    calls = out[1]["tool_calls"]
    assert calls[0]["extra_content"]["google"]["thought_signature"] == "PLACEHOLDER"
    assert calls[1]["extra_content"]["google"]["thought_signature"] == "REAL"
    assert "extra_content" not in foreign  # the caller's messages are not mutated
    assert out[0] is history[0] and out[2] is history[2]


async def test_a_provider_with_a_signature_receives_the_patched_history():
    seen = []

    class Spy(FakeCreate):
        async def __call__(self, *, model, messages, tools=None, reasoning_effort=None):
            seen.append(messages)
            return await super().__call__(
                model=model,
                messages=messages,
                tools=tools,
                reasoning_effort=reasoning_effort,
            )

    create = Spy([])
    chain = LLMChain(
        [
            ProviderSpec(
                name="gemini",
                client=fake_client(create),
                models=("g",),
                tool_call_signature="PLACEHOLDER",
            )
        ],
        AIConfig(),
        clock=Clock(),
    )
    msgs = [{"role": "assistant", "content": None, "tool_calls": [{"id": "a"}]}]
    await chain.complete(msgs, [])
    assert (
        seen[0][0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
        == "PLACEHOLDER"
    )
    assert "extra_content" not in msgs[0]["tool_calls"][0]
