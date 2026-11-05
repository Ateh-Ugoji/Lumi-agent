"""``AIConfig.from_env``: the .env variables must change what the code actually uses."""

from __future__ import annotations

from dataclasses import fields

import pytest

from lumi_ai.config import ENV_FIELDS, AIConfig
from lumi_ai.providers import build_chain, build_provider_specs
from lumi_ai.providers.audio import Transcriber
from lumi_ai.tests.providers._fakes import FakeCreate, fake_client


def test_every_env_field_is_a_real_config_field():
    assert set(ENV_FIELDS) <= {f.name for f in fields(AIConfig)}


def test_empty_environment_gives_the_defaults():
    assert AIConfig.from_env({}) == AIConfig()
    assert (
        AIConfig.from_env({"GROQ_MODEL_LARGE": "  ", "LLM_TIMEOUT_SECONDS": ""})
        == AIConfig()
    )


def test_env_values_are_typed_and_unknown_variables_ignored():
    cfg = AIConfig.from_env(
        {
            "GROQ_MODEL_LARGE": "big",
            "PROVIDER_COOLDOWN_SECONDS": "12",
            "PROVIDER_COOLDOWN_MAX_SECONDS": "40.5",
            "LLM_TIMEOUT_SECONDS": "7",
            "WHISPER_MODEL": "w-1",
            "MAX_REQUEST_TOKENS": "1",  # tuning stays in code
            "PATH": "/bin",
        }
    )
    assert cfg.groq_model_large == "big" and cfg.whisper_model == "w-1"
    assert cfg.provider_cooldown_seconds == 12.0
    assert cfg.provider_cooldown_max_seconds == 40.5
    assert cfg.llm_timeout_seconds == 7.0
    assert cfg.max_request_tokens == AIConfig().max_request_tokens


def test_malformed_number_names_the_variable():
    with pytest.raises(ValueError, match="LLM_TIMEOUT_SECONDS='soon'"):
        AIConfig.from_env({"LLM_TIMEOUT_SECONDS": "soon"})


def test_from_env_reads_os_environ(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "or/x")
    assert AIConfig.from_env().openrouter_model == "or/x"


async def test_changing_the_env_changes_the_model_the_chain_calls():
    async def used_models(env: dict[str, str], **call) -> list[str]:
        create = FakeCreate([])
        cfg = AIConfig.from_env({"GROQ_API_KEY": "k", **env})
        chain = build_chain(cfg, client_factory=lambda *_: fake_client(create))
        await chain.complete([{"role": "user", "content": "hi"}], [], **call)
        return create.models

    assert await used_models({}) == [AIConfig().groq_model_large]
    assert await used_models({"GROQ_MODEL_LARGE": "my/large"}) == ["my/large"]
    assert await used_models({"GROQ_MODEL_SMALL": "my/small"}, tier="small") == [
        "my/small"
    ]


def test_env_models_reach_the_fallback_and_openrouter_candidates():
    cfg = AIConfig.from_env(
        {
            "GROQ_API_KEY": "g",
            "OPENROUTER_API_KEY": "o",
            "GROQ_MODEL_LARGE": "L",
            "GROQ_MODEL_FALLBACK": "F",
            "OPENROUTER_MODEL": "R",
        }
    )
    by_name = {s.name: s.models for s in build_provider_specs(cfg)}
    assert by_name == {"groq": ("L", "F"), "openrouter": ("R",)}


def test_env_whisper_model_is_the_one_transcribe_uses():
    cfg = AIConfig.from_env({"WHISPER_MODEL": "w-env"})
    assert Transcriber(cfg, client=object())._config.whisper_model == "w-env"


async def test_env_cooldown_seconds_set_how_long_a_failed_model_rests():
    from lumi_ai.providers.chain import LLMChain
    from lumi_ai.tests.providers._fakes import Clock, api_error

    clock = Clock()
    create = FakeCreate([api_error(429)])
    cfg = AIConfig.from_env({"GROQ_API_KEY": "k", "PROVIDER_COOLDOWN_SECONDS": "7"})
    specs = build_provider_specs(cfg, lambda *_: fake_client(create))
    chain = LLMChain(specs, cfg, clock=clock)
    await chain.complete(
        [{"role": "user", "content": "hi"}], []
    )  # 429 on the large model
    assert chain.is_resting("groq", cfg.groq_model_large)
    clock.t += 6
    assert chain.is_resting("groq", cfg.groq_model_large)
    clock.t += 2
    assert not chain.is_resting("groq", cfg.groq_model_large)


def test_video_timeout_seconds_is_read_from_the_environment():
    assert (
        AIConfig.from_env({"VIDEO_TIMEOUT_SECONDS": "45"}).video_timeout_seconds == 45.0
    )


def test_an_empty_video_timeout_means_the_default():
    default = AIConfig().video_timeout_seconds
    assert (
        AIConfig.from_env({"VIDEO_TIMEOUT_SECONDS": ""}).video_timeout_seconds
        == default
    )
    assert (
        AIConfig.from_env({"VIDEO_TIMEOUT_SECONDS": "  "}).video_timeout_seconds
        == default
    )


def test_a_malformed_video_timeout_names_the_variable():
    with pytest.raises(ValueError, match="video_timeout_seconds|VIDEO_TIMEOUT_SECONDS"):
        AIConfig.from_env({"VIDEO_TIMEOUT_SECONDS": "soon"})
