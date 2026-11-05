import logging
from dataclasses import dataclass

import neatlogs
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from app.config import get_settings

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

OPENLUX_BASE_URL = "https://api.openlux.ai/v1"

# Same IDs on Groq and OpenRouter, so a tier override applies to whichever provider answers.
TIER_MODELS = {"small": "openai/gpt-oss-20b", "large": "openai/gpt-oss-120b"}

# Groq carries TWO chat models in chain: openai/gpt-oss-120b FIRST (reasoning
# model, ~8,000-input-token wall, verified full tool-calling and reasoning_effort),
# then qwen/qwen3.8-27b (~7,000 wall — 413 request-too-large above it, and its
# daily-token quota is nearly exhausted, so it is the FALLBACK, not the default).
# A gpt-oss failure is answered on the second Groq model instead of burning the
# OpenRouter leg (which is 402-limited by an empty credit balance anyway).
# Explicit `model=` callers (repurpose tiering) pin a single model and skip this.
GROQ_FALLBACK_MODEL = "qwen/qwen3.8-27b"

NEATLOGS_ENDPOINT = "https://ingest.neatlogs.com"
NEATLOGS_WORKFLOW_NAME = "lumi"


@dataclass
class ProviderConfig:
    name: str
    client: AsyncOpenAI
    # Models tried in order on this provider. An explicit model= argument
    # overrides the chain with a single pinned candidate (tier routing).
    models: list[str]


_providers: list[ProviderConfig] | None = None

_audio_client: AsyncOpenAI | None = None


def get_audio_provider() -> AsyncOpenAI:
    """Client for Groq's audio endpoints (speech-to-text).

    Kept separate from `get_providers()`: those are neatlogs-wrapped *chat*
    clients with model tiering, while audio rides Groq's `audio.*` namespace
    and is exercised far less often. Built lazily, once. TTS is browser-local
    for now — this Groq account exposes no TTS model (verified via
    `GET /openai/v1/models`), so there is no server-side speak path.
    """
    global _audio_client
    if _audio_client is None:
        settings = get_settings()
        _audio_client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL)
    return _audio_client


def _init_tracing(settings) -> None:
    neatlogs.init(
        api_key=settings.neatlogs_api_key,
        endpoint=NEATLOGS_ENDPOINT,
        workflow_name=NEATLOGS_WORKFLOW_NAME,
        capture_logs=True,
    )


def get_providers() -> list[ProviderConfig]:
    global _providers
    if _providers is None:
        settings = get_settings()
        _init_tracing(settings)  # must init before wrap()

        _providers = []
        if settings.openlux_api_key:
            _providers.append(
                ProviderConfig(
                    name="openlux",
                    client=neatlogs.wrap(
                        AsyncOpenAI(api_key=settings.openlux_api_key, base_url=OPENLUX_BASE_URL),
                        provider="openlux",
                    ),
                    models=[settings.openlux_model],
                )
            )
        _providers += [
            ProviderConfig(
                name="groq",
                client=neatlogs.wrap(
                    AsyncOpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL), provider="groq"
                ),
                models=[GROQ_MODEL, GROQ_FALLBACK_MODEL],
            ),
            ProviderConfig(
                name="openrouter",
                client=neatlogs.wrap(
                    AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=OPENROUTER_BASE_URL),
                    provider="openrouter",
                ),
                models=[OPENROUTER_MODEL],
            ),
        ]
    return _providers


async def chat_completion_with_provider(
    messages: list[ChatCompletionMessageParam],
    tools: list[dict],
    model: str | None = None,
    *,
    effort: str | None = None,
) -> tuple[ChatCompletion, str]:
    """Try each provider in order (OpenLux when configured, then Groq, then OpenRouter),
    and within a provider try each of its models in order, falling back on any API
    error. Groq's chain is openai/gpt-oss-120b -> qwen3.8-27b, so a failure on the
    primary reasoning model is retried on the second Groq model BEFORE the chain
    moves to OpenRouter.

    An explicit `model` argument pins a single candidate per provider (repurpose
    tiering relies on this: "small" must never be silently upgraded).

    `effort` (keyword-only, default None) is forwarded as `reasoning_effort`.
    It is opt-in: models that reject the parameter answer 400, so the SAME
    candidate is retried once WITHOUT it before the chain advances — a 400 from
    the parameter never costs the provider/model slot.

    Returns the completion and the name of the provider that answered.
    """
    last_error: Exception | None = None

    for provider in get_providers():
        candidates = [model] if model else provider.models
        for index, candidate in enumerate(candidates):
            payload: dict = {
                "model": candidate,
                "messages": messages,
                "tools": tools or None,
            }
            attempts = [payload]
            if effort is not None:
                attempts = [{**payload, "reasoning_effort": effort}, payload]
            completion: ChatCompletion | None = None
            attempt_error: Exception | None = None
            for attempt in attempts:
                try:
                    completion = await provider.client.chat.completions.create(**attempt)
                except openai.APIError as exc:
                    attempt_error = exc
                    # Retry without reasoning_effort only when THAT parameter
                    # was the last thing added and the error is a 400.
                    if (
                        effort is None
                        or "reasoning_effort" not in attempt
                        or getattr(exc, "status_code", None) != 400
                    ):
                        break
                    logger.warning(
                        "provider %s model %s rejected reasoning_effort, retrying without it: %s",
                        provider.name,
                        candidate,
                        exc,
                    )
                else:
                    break
            if completion is None:
                exc = attempt_error if attempt_error is not None else RuntimeError("no attempt made")
                next_step = "next model" if index + 1 < len(candidates) else "next provider"
                logger.warning(
                    "provider %s model %s failed, trying %s: %s",
                    provider.name,
                    candidate,
                    next_step,
                    exc,
                )
                neatlogs.log(
                    "provider {provider} model {model} failed",
                    provider=provider.name,
                    model=candidate,
                    error=str(exc),
                )
                last_error = exc
                continue
            if index:
                logger.info(
                    "provider %s answered with fallback model %s", provider.name, candidate
                )
            return completion, provider.name

    raise RuntimeError("all LLM providers failed") from last_error


async def chat_completion_with_fallback(
    messages: list[ChatCompletionMessageParam], tools: list[dict], *, effort: str | None = None
) -> ChatCompletion:
    completion, _ = await chat_completion_with_provider(messages, tools, effort=effort)
    return completion
