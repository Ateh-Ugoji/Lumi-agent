"""Provider model-chain fallback (payload walls + rate windows).

Groq carries two chat models in chain — openai/gpt-oss-120b FIRST (the primary
reasoning model, ~8,000 input-token wall, full tool-calling), then
qwen3.8-27b (~7,000 wall; its daily-token quota is nearly exhausted, so it is
the fallback). Any `openai.APIError` (413 request-too-large, 429 rate window,
5xx) advances model-then-provider, so an over-large tool turn is retried on
the second Groq model before the chain burns the OpenRouter leg. An explicit
`model=` argument pins a single candidate per provider (repurpose tiering must
never silently upgrade "small"). `effort=` forwards `reasoning_effort`; a 400
from that parameter retries the SAME candidate once without it.
"""

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.agent import providers


def _api_error(status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return openai.APIStatusError(f"status {status}", response=response, body=None)


class _FakeCreate:
    """Scripted completions.create: raises per script entry, else 'answers'."""

    def __init__(self, script: list):
        self.script = list(script)
        self.models_requested: list[str] = []
        self.efforts_requested: list[str | None] = []

    async def __call__(self, *, model, messages, tools=None, reasoning_effort=None):
        self.models_requested.append(model)
        self.efforts_requested.append(reasoning_effort)
        action = self.script.pop(0) if self.script else "ok"
        if isinstance(action, Exception):
            raise action
        return SimpleNamespace(model=model)


@pytest.fixture
def provider_factory(monkeypatch):
    """Build a patched provider chain from (name, models, script) specs."""
    created: dict[str, _FakeCreate] = {}

    def _apply(specs: list[tuple[str, list[str], list]]) -> list:
        configs = []
        for name, models, script in specs:
            create = _FakeCreate(script)
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            configs.append(providers.ProviderConfig(name=name, client=client, models=models))
            created[name] = create
        monkeypatch.setattr(providers, "get_providers", lambda: configs)
        return configs

    _apply.created = created
    return _apply


@pytest.fixture(autouse=True)
def _neatlogs_stub(monkeypatch):
    # neatlogs.log is called on every fallback; keep tests hermetic (no SDK side effects).
    monkeypatch.setattr(providers, "neatlogs", SimpleNamespace(log=lambda *a, **k: None))


async def test_groq_413_falls_back_to_second_model(provider_factory):
    provider_factory([("groq", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"], [_api_error(413), "ok"])])

    completion, name = await providers.chat_completion_with_provider(
        [{"role": "user", "content": "hi"}], tools=[]
    )

    assert name == "groq"
    assert completion.model == "qwen/qwen3.8-27b"
    assert provider_factory.created["groq"].models_requested == [
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
    ]


async def test_second_model_failure_moves_to_next_provider(provider_factory):
    provider_factory([
        ("groq", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"], [_api_error(413), _api_error(429)]),
        ("openrouter", ["meta-llama/llama-3.3-70b-instruct"], ["ok"]),
    ])

    completion, name = await providers.chat_completion_with_provider(
        [{"role": "user", "content": "hi"}], tools=[]
    )

    assert name == "openrouter"
    assert completion.model == "meta-llama/llama-3.3-70b-instruct"
    assert provider_factory.created["groq"].models_requested == [
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
    ]


async def test_single_model_provider_moves_on_after_one_error(provider_factory):
    # OpenLux is dead (401); it carries one model, so an auth error skips it entirely.
    provider_factory([
        ("openlux", ["qwen3.8-27b"], [_api_error(401)]),
        ("groq", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"], ["ok"]),
    ])

    _, name = await providers.chat_completion_with_provider(
        [{"role": "user", "content": "hi"}], tools=[]
    )

    assert name == "groq"
    assert provider_factory.created["openlux"].models_requested == ["qwen3.8-27b"]
    assert provider_factory.created["groq"].models_requested == ["openai/gpt-oss-120b"]


async def test_explicit_model_pins_a_single_candidate_per_provider(provider_factory):
    # Repurpose tiering passes model=TIER_MODELS[tier]; "small" must never be
    # silently upgraded to the second chain entry.
    provider_factory([("groq", ["openai/gpt-oss-20b", "openai/gpt-oss-120b"], [_api_error(500)])])

    with pytest.raises(RuntimeError, match="all LLM providers failed"):
        await providers.chat_completion_with_provider(
            [{"role": "user", "content": "hi"}], tools=[], model="openai/gpt-oss-20b"
        )

    assert provider_factory.created["groq"].models_requested == ["openai/gpt-oss-20b"]


async def test_all_providers_fail_raises_runtime_error_with_cause(provider_factory):
    provider_factory([
        ("groq", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"], [_api_error(413), _api_error(429)]),
        ("openrouter", ["meta-llama/llama-3.3-70b-instruct"], [_api_error(402)]),
    ])

    with pytest.raises(RuntimeError, match="all LLM providers failed") as excinfo:
        await providers.chat_completion_with_provider(
            [{"role": "user", "content": "hi"}], tools=[]
        )

    assert isinstance(excinfo.value.__cause__, openai.APIStatusError)


def test_groq_chain_is_gpt_oss_then_qwen(monkeypatch):
    monkeypatch.setattr(providers, "_init_tracing", lambda settings: None)
    monkeypatch.setattr(
        providers,
        "neatlogs",
        SimpleNamespace(wrap=lambda client, provider=None: client, log=lambda *a, **k: None),
    )
    monkeypatch.setattr(
        providers,
        "get_settings",
        lambda: SimpleNamespace(
            openlux_api_key=None,
            groq_api_key="test",
            openrouter_api_key="test",
            openlux_model="unused",
        ),
    )
    monkeypatch.setattr(providers, "_providers", None)

    configs = {p.name: p for p in providers.get_providers()}

    assert "openlux" not in configs  # unset key -> not in the chain
    # gpt-oss-120b FIRST (reasoning model, verified reasoning_effort), qwen last
    # resort (quota nearly exhausted) — both literals, neither derives from TIER_MODELS.
    assert configs["groq"].models == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
    assert providers.GROQ_MODEL == "openai/gpt-oss-120b"
    assert providers.GROQ_FALLBACK_MODEL == "qwen/qwen3.8-27b"
    assert configs["openrouter"].models == [providers.OPENROUTER_MODEL]


async def test_effort_400_retries_same_model_without_reasoning_effort(provider_factory):
    # A model that rejects reasoning_effort answers 400; the SAME candidate is
    # retried once without the parameter before the chain advances.
    provider_factory([("groq", ["openai/gpt-oss-120b"], [_api_error(400), "ok"])])

    completion, name = await providers.chat_completion_with_provider(
        [{"role": "user", "content": "hi"}], tools=[], effort="low"
    )

    assert name == "groq"
    assert completion.model == "openai/gpt-oss-120b"
    create = provider_factory.created["groq"]
    assert create.models_requested == ["openai/gpt-oss-120b", "openai/gpt-oss-120b"]
    assert create.efforts_requested == ["low", None]


async def test_effort_non_400_does_not_retry_same_model(provider_factory):
    # 401 with effort sent advances immediately — no wasted duplicate request.
    provider_factory([
        ("groq", ["openai/gpt-oss-120b"], [_api_error(401)]),
        ("openrouter", ["meta-llama/llama-3.3-70b-instruct"], ["ok"]),
    ])

    _, name = await providers.chat_completion_with_provider(
        [{"role": "user", "content": "hi"}], tools=[], effort="low"
    )

    assert name == "openrouter"
    assert provider_factory.created["groq"].models_requested == ["openai/gpt-oss-120b"]
    assert provider_factory.created["groq"].efforts_requested == ["low"]


async def test_fallback_forwards_effort(provider_factory):
    provider_factory([("groq", ["openai/gpt-oss-120b"], ["ok"])])

    await providers.chat_completion_with_fallback(
        [{"role": "user", "content": "hi"}], [], effort="low"
    )

    assert provider_factory.created["groq"].efforts_requested == ["low"]


async def test_no_effort_sends_no_reasoning_effort_key(provider_factory):
    provider_factory([("groq", ["openai/gpt-oss-120b"], ["ok"])])

    await providers.chat_completion_with_fallback(
        [{"role": "user", "content": "hi"}], []
    )

    assert provider_factory.created["groq"].efforts_requested == [None]
