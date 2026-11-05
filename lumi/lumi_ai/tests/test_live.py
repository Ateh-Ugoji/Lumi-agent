"""Real-provider checks (T11). Excluded by default; run one at a time and only on purpose:

    LUMI_RUN_LIVE=1 uv run pytest -m live lumi_ai/tests/test_live.py -k groq

Each test needs its own key (read from the environment or ``lumi/.env``), uses the smallest
request that proves the point, and skips (never fails) when the key is missing or the provider
answers that the account has no balance or quota. Nothing here runs in ``-m "not live"``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import get_args

import httpx
import pytest

from lumi_ai.config import AIConfig
from lumi_ai.keys import build_probes
from lumi_ai.ports import ProbeStatus
from lumi_ai.providers import (
    AllProvidersFailed,
    Transcriber,
    build_chain,
)
from lumi_ai.providers.urls import OPENROUTER_BASE_URL

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).parent / "fixtures"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
GET_TIME = {
    "type": "function",
    "function": {
        "name": "get_launch_day",
        "description": "Returns the day of the week of the next product launch.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}


def _dotenv() -> dict[str, str]:
    """``lumi/.env`` values; the real environment wins."""
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    return {**values, **os.environ}


@pytest.fixture
def config() -> AIConfig:
    return AIConfig.from_env(_dotenv())


def _skip_if_billing(exc: AllProvidersFailed) -> None:
    """A 401/402/429 is the account's state, not a product failure."""
    kinds = {a.kind for a in exc.attempts}
    if kinds & {"auth", "payment", "rate_limit", "quota"}:
        pytest.skip(f"provider refused the account: {sorted(kinds)}")


@pytest.mark.asyncio
async def test_groq_full_tool_calling_round_trip(config):
    """Model asks for a tool, gets the result, and answers with it."""
    if not config.groq_api_key:
        pytest.skip("GROQ_API_KEY is not set")
    chain = build_chain(
        AIConfig(groq_api_key=config.groq_api_key, **_groq_models(config))
    )
    messages = [
        {
            "role": "user",
            "content": "Call get_launch_day, then tell me the day in one short sentence.",
        }
    ]
    try:
        first = await chain.complete(messages, [GET_TIME], tier="large")
    except AllProvidersFailed as exc:
        _skip_if_billing(exc)
        raise
    message = first.completion.choices[0].message
    assert message.tool_calls, "the model did not call the tool"
    call = message.tool_calls[0]
    assert call.function.name == "get_launch_day"
    messages.append(
        {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
            ],
        }
    )
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps({"day": "Friday"}),
        }
    )
    final = await chain.complete(messages, [GET_TIME], tier="large")
    assert "friday" in (final.completion.choices[0].message.content or "").lower()


def _groq_models(config: AIConfig) -> dict[str, str]:
    return {
        "groq_model_large": config.groq_model_large,
        "groq_model_small": config.groq_model_small,
        "groq_model_fallback": config.groq_model_fallback,
    }


def _free_openrouter_models() -> list[str]:
    """Free models that accept tools, from OpenRouter's public catalog (no key needed)."""
    data = httpx.get(f"{OPENROUTER_BASE_URL}/models", timeout=20).json()["data"]
    return [
        m["id"]
        for m in data
        if m["id"].endswith(":free") and "tools" in m.get("supported_parameters", [])
    ]


def test_the_default_openrouter_model_is_in_the_public_catalog(config):
    """The configured id must exist today (model ids disappear). Costs nothing: catalog only."""
    ids = {
        m["id"]
        for m in httpx.get(f"{OPENROUTER_BASE_URL}/models", timeout=20).json()["data"]
    }
    assert config.openrouter_model in ids


@pytest.mark.asyncio
async def test_openrouter_answers_with_a_free_model(config):
    if not config.openrouter_api_key:
        pytest.skip("OPENROUTER_API_KEY is not set")
    candidates = _free_openrouter_models()
    if not candidates:
        pytest.skip("OpenRouter lists no free model with tool support today")
    last: AllProvidersFailed | None = None
    for model in candidates[
        :3
    ]:  # free models are often busy; three tries, then give up
        chain = build_chain(
            AIConfig(
                openrouter_api_key=config.openrouter_api_key, openrouter_model=model
            )
        )
        try:
            result = await chain.complete(
                [{"role": "user", "content": "Reply with the single word: ok"}]
            )
        except AllProvidersFailed as exc:
            last = exc
            continue
        assert result.provider == "openrouter" and result.model == model
        assert (result.completion.choices[0].message.content or "").strip()
        return
    assert last is not None
    _skip_if_billing(last)
    raise last


@pytest.mark.asyncio
async def test_whisper_transcribes_a_two_second_clip(config):
    """Fixture: 2 s of synthetic speech ("We ship the new launch on Friday.")."""
    if not config.groq_api_key:
        pytest.skip("GROQ_API_KEY is not set")
    audio = (FIXTURES / "we_ship_on_friday.wav").read_bytes()
    result = await Transcriber(config).transcribe(audio)
    assert result.model == config.whisper_model
    assert "friday" in result.text.lower()


@pytest.mark.asyncio
async def test_the_probes_report_a_real_answer_for_every_configured_key(config):
    probes = [p for p in build_probes(config) if p.name != "chroma"]
    results = {p.name: await p.run() for p in probes}
    configured = {
        "groq": config.groq_api_key,
        "openrouter": config.openrouter_api_key,
        "openlux": config.openlux_api_key,
    }
    for name, key in configured.items():
        if key and name in results:
            assert results[name].status in get_args(ProbeStatus)
            assert key not in results[name].detail  # a probe never prints a key
