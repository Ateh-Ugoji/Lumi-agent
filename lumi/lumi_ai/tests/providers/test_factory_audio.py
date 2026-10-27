import httpx
import pytest

from lumi_ai.config import AIConfig
from lumi_ai.providers import (
    AudioNotConfigured,
    AudioTooLarge,
    EmptyAudio,
    Transcriber,
    build_chain,
    build_provider_specs,
)
from lumi_ai.providers.audio import MAX_AUDIO_BYTES, AudioError


def test_importing_and_building_without_any_key_is_safe():
    chain = build_chain(AIConfig())
    assert chain.providers == ()


def test_chain_order_and_models_from_config():
    cfg = AIConfig(
        groq_api_key="g",
        openrouter_api_key="o",
        openlux_api_key="x",
        groq_model_large="L",
        groq_model_fallback="F",
        openrouter_model="R",
    )
    specs = {s.name: s for s in build_provider_specs(cfg)}
    assert list(specs) == ["openlux", "groq", "openrouter"]
    assert specs["groq"].models == ("L", "F")
    assert specs["groq"].max_request_tokens == cfg.max_request_tokens
    assert specs["openrouter"].models == ("R",)
    assert specs["openlux"].accepts_pinned_model is False


def test_providers_without_a_key_are_left_out():
    specs = build_provider_specs(AIConfig(groq_api_key="g"))
    assert [s.name for s in specs] == ["groq"]


def test_defaults_match_the_legacy_chain():
    cfg = AIConfig(groq_api_key="g")
    assert build_provider_specs(cfg)[0].models == (
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
    )


class _Transcriptions:
    def __init__(self, *, fail=False):
        self.fail, self.calls = fail, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise httpx.ConnectError("boom")
        return type("R", (), {"text": "  hola mundo  "})()


class _Client:
    def __init__(self, t):
        self.audio = type("A", (), {"transcriptions": t})()


async def test_transcribe_trims_and_uses_configured_model():
    t = _Transcriptions()
    out = await Transcriber(AIConfig(whisper_model="w"), client=_Client(t)).transcribe(
        b"\x00" * 10, "a.webm", "audio/webm"
    )
    assert out.text == "hola mundo" and out.model == "w"
    assert t.calls[0]["file"] == ("a.webm", b"\x00" * 10, "audio/webm")


async def test_transcribe_guards():
    tr = Transcriber(AIConfig(), client=_Client(_Transcriptions()))
    with pytest.raises(EmptyAudio):
        await tr.transcribe(b"")
    with pytest.raises(AudioTooLarge):
        await tr.transcribe(b"0" * (MAX_AUDIO_BYTES + 1))


async def test_transcribe_without_key_is_a_typed_error():
    with pytest.raises(AudioNotConfigured):
        await Transcriber(AIConfig()).transcribe(b"1")


async def test_transcribe_failure_is_typed_and_keeps_cause():
    tr = Transcriber(AIConfig(), client=_Client(_Transcriptions(fail=True)))
    with pytest.raises(AudioError) as info:
        await tr.transcribe(b"1")
    assert isinstance(info.value.__cause__, httpx.ConnectError)
