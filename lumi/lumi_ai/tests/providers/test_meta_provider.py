from unittest.mock import AsyncMock, patch

import httpx

from lumi_ai.config import AIConfig
from lumi_ai.providers import (
    LLMChain,
    ProviderSpec,
    Transcriber,
    build_provider_specs,
)
from lumi_ai.providers.urls import META_BASE_URL
from lumi_ai.tests.providers._fakes import (
    FakeCreate,
    api_error,
    fake_client,
)

MSG = [{"role": "user", "content": "Analyze this post"}]


def test_meta_provider_spec_is_built_when_key_is_set():
    cfg = AIConfig(
        meta_api_key="meta-secret-key",
        groq_api_key="groq-secret-key",
    )
    specs = {s.name: s for s in build_provider_specs(cfg)}
    assert "meta" in specs
    assert specs["meta"].models == ("muse-wonder-1.0", "muse-spark-1.3")
    assert specs["meta"].tier_models == {
        "reasoning": "muse-wonder-1.0",
        "large": "muse-wonder-1.0",
        "small": "muse-spark-1.3",
    }


def test_meta_provider_order_before_groq():
    cfg = AIConfig(
        meta_api_key="meta-key",
        groq_api_key="groq-key",
        gemini_api_key="gem-key",
        openrouter_api_key="or-key",
    )
    specs = [s.name for s in build_provider_specs(cfg)]
    assert specs == ["meta", "groq", "gemini", "openrouter"]


async def test_tier_reasoning_routes_to_meta_wonder():
    meta_create = FakeCreate(["ok"])
    groq_create = FakeCreate([])

    meta_spec = ProviderSpec(
        name="meta",
        client=fake_client(meta_create),
        models=("muse-wonder-1.0", "muse-spark-1.3"),
        tier_models={
            "reasoning": "muse-wonder-1.0",
            "large": "muse-wonder-1.0",
            "small": "muse-spark-1.3",
        },
    )
    groq_spec = ProviderSpec(
        name="groq",
        client=fake_client(groq_create),
        models=("openai/gpt-oss-120b", "qwen/qwen3.8-27b"),
        tier_models={
            "reasoning": "openai/gpt-oss-120b",
            "large": "openai/gpt-oss-120b",
            "small": "openai/gpt-oss-20b",
        },
    )

    chain = LLMChain([meta_spec, groq_spec], AIConfig(meta_api_key="k"))
    res = await chain.complete(MSG, [], tier="reasoning")

    assert res.provider == "meta"
    assert res.model == "muse-wonder-1.0"
    assert meta_create.models == ["muse-wonder-1.0"]
    assert groq_create.models == []


async def test_meta_failure_falls_back_to_groq_reasoning():
    meta_create = FakeCreate([api_error(500)])
    groq_create = FakeCreate(["ok"])

    meta_spec = ProviderSpec(
        name="meta",
        client=fake_client(meta_create),
        models=("muse-wonder-1.0", "muse-spark-1.3"),
        tier_models={
            "reasoning": "muse-wonder-1.0",
            "large": "muse-wonder-1.0",
            "small": "muse-spark-1.3",
        },
    )
    groq_spec = ProviderSpec(
        name="groq",
        client=fake_client(groq_create),
        models=("openai/gpt-oss-120b", "qwen/qwen3.8-27b"),
        tier_models={
            "reasoning": "openai/gpt-oss-120b",
            "large": "openai/gpt-oss-120b",
            "small": "openai/gpt-oss-20b",
        },
    )

    chain = LLMChain([meta_spec, groq_spec], AIConfig(meta_api_key="k"))
    res = await chain.complete(MSG, [], tier="reasoning")

    assert res.provider == "groq"
    assert res.model == "openai/gpt-oss-120b"
    assert len(res.attempts) == 1
    assert res.attempts[0].provider == "meta"


async def test_meta_transcriber_calls_meta_asr_endpoint():
    cfg = AIConfig(meta_api_key="meta-asr-key")
    tr = Transcriber(cfg)

    mock_response = httpx.Response(
        200,
        json={"transcript": "hello from meta voice", "audioDurationMs": 1500},
        request=httpx.Request("POST", f"{META_BASE_URL}/asr/transcribe"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        out = await tr.transcribe(b"\x00" * 100, filename="test.wav", content_type="audio/wav")

    assert out.text == "hello from meta voice"
    assert out.model == "muse-voice-transcribe-1.0"
    assert mock_post.called
    _args, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer meta-asr-key"
    assert "audio" in kwargs["files"]
    assert "request" in kwargs["files"]
