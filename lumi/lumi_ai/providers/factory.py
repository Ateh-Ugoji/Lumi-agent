"""Builds the provider chain from an :class:`AIConfig`. No keys: an empty chain, not a crash."""

from __future__ import annotations

from collections.abc import Callable

from openai import AsyncOpenAI

from lumi_ai import observability
from lumi_ai.config import AIConfig
from lumi_ai.providers.chain import LLMChain, ProviderSpec, UsageSink
from lumi_ai.providers.urls import GROQ_BASE_URL, OPENLUX_BASE_URL, OPENROUTER_BASE_URL

ClientFactory = Callable[[str, str, float], object]


def _openai_client(api_key: str, base_url: str, timeout: float) -> object:
    # max_retries=0: the chain is the retry policy; SDK back-off would delay the fallback.
    return AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0
    )


def build_provider_specs(
    config: AIConfig, client_factory: ClientFactory = _openai_client
) -> list[ProviderSpec]:
    """Providers with a key, in order: OpenLux (optional), Groq, OpenRouter."""
    timeout = config.llm_timeout_seconds
    specs: list[ProviderSpec] = []

    def add(
        name: str, key: str | None, url: str, models: tuple[str, ...], **extra: object
    ) -> None:
        if not key:
            return
        client = observability.wrap_client(client_factory(key, url, timeout), name)
        specs.append(ProviderSpec(name=name, client=client, models=models, **extra))  # type: ignore[arg-type]

    add(
        "openlux",
        config.openlux_api_key,
        OPENLUX_BASE_URL,
        (config.openlux_model,),
        accepts_pinned_model=False,
    )
    add(
        "groq",
        config.groq_api_key,
        GROQ_BASE_URL,
        (config.groq_model_large, config.groq_model_fallback),
    )
    add(
        "openrouter",
        config.openrouter_api_key,
        OPENROUTER_BASE_URL,
        (config.openrouter_model,),
    )
    return specs


def build_chain(
    config: AIConfig,
    *,
    usage_sink: UsageSink | None = None,
    client_factory: ClientFactory = _openai_client,
) -> LLMChain:
    """Build the chain. Starts neatlogs first when a key is set, so ``wrap`` sees it."""
    observability.init_tracing(config)
    return LLMChain(
        build_provider_specs(config, client_factory), config, usage_sink=usage_sink
    )
