"""AIConfig: every model id, limit and threshold of the AI package, in one place.

Django builds it from settings with :meth:`AIConfig.from_mapping`; nothing in ``lumi_ai`` reads
the environment by itself. Defaults are the values the legacy code used (``lumi/app/agent``).
Model ids are configuration, not code: ``check_keys`` validates them against each provider's
real model list.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True, slots=True)
class AIConfig:
    # --- models (the legacy defaults; unverified against today's catalogs) ---
    groq_model_large: str = "openai/gpt-oss-120b"
    groq_model_small: str = "openai/gpt-oss-20b"
    groq_model_fallback: str = "qwen/qwen3.8-27b"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct"
    openlux_model: str = "qwen3.8-27b"
    whisper_model: str = "whisper-large-v3-turbo"

    # --- keys (None = absent; the callers decide whether that is fatal) ---
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    openlux_api_key: str | None = None
    typesafe_api_key: str | None = None
    neatlogs_api_key: str | None = None
    chroma_api_key: str | None = None
    chroma_tenant: str | None = None
    chroma_database: str | None = None
    chroma_path: str = ".chroma"
    video_provider: str | None = None
    video_api_key: str | None = None

    # --- agent loop (legacy lumi/app/agent/loop.py) ---
    max_tool_iterations: int = 6
    max_history_messages: int = 10
    tool_context_char_limit: int = 4_000
    old_tool_context_char_limit: int = 1_200
    max_request_tokens: int = 6_700
    est_chars_per_token: float = 3.5
    tool_timeout_seconds: float = 120.0
    sufficiency_threshold: float = 0.75
    sufficiency_min_tools: int = 2  # tool calls before the judge is asked "enough?"
    mcp_discovery_timeout_seconds: float = 3.0
    memory_worthy_threshold: float = 0.6

    # --- providers ---
    provider_cooldown_seconds: float = (
        300.0  # after a 401/402/403/429 a candidate rests this long
    )
    provider_cooldown_max_seconds: float = (
        900.0  # ceiling when a provider sends Retry-After
    )
    llm_timeout_seconds: float = 60.0

    # --- turn classifier, stage 2 ---
    turn_class_jev_enabled: bool = False
    turn_class_jev_timeout_ms: int = 1_500
    turn_class_jev_high: float = 0.7
    turn_class_jev_low: float = 0.4

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> AIConfig:
        """Build from a flat mapping with lowercase field names; unknown keys are an error.

        Empty strings count as unset, so ``VIDEO_PROVIDER=`` in ``.env`` turns video off.
        """
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown AIConfig keys: {', '.join(unknown)}")
        cleaned = {k: v for k, v in values.items() if v is not None and v != ""}
        return cls(**cleaned)
