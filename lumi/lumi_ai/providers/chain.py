"""The LLM provider chain: ordered providers, ordered models, cooldown, usage log.

Behaviour kept from the legacy ``app/agent/providers.py``:

* Providers are tried in order; within a provider, models in order.
* An explicit ``model=`` (or ``tier=``) pins ONE candidate per provider, so a "small" request
  is never silently upgraded.
* ``effort`` is sent as ``reasoning_effort``. A 400 retries the SAME candidate once without it.

New in lumi_ai:

* A candidate that answered 401/402/403/429 rests for ``provider_cooldown_seconds`` (or the
  provider's ``Retry-After``, capped), so an empty OpenRouter balance is not paid for with a
  failed call on every turn. When every candidate is resting, they are tried anyway, soonest
  expiry first: a failed call is cheap, a missing answer is not.
* A provider with a known input-token wall (Groq) is skipped, without a call, when the request
  is estimated to be over it.
* Every call (success or failure) is reported to a ``UsageSink``.
* Typed errors: :class:`AllProvidersFailed` carries every attempt.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai
from openai.types.chat import ChatCompletion

from lumi_ai.config import AIConfig
from lumi_ai.providers.errors import (
    COOLDOWN_KINDS,
    AllProvidersFailed,
    Attempt,
    FailureKind,
    NoProviderConfigured,
    RequestTooLarge,
)

logger = logging.getLogger(__name__)


class ChatClient(Protocol):
    """The slice of ``openai.AsyncOpenAI`` the chain uses (also what tests fake)."""

    chat: Any  # exposes ``chat.completions.create(**payload)``


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    name: str
    client: ChatClient
    models: tuple[str, ...]
    #: Input-token wall of this provider, or ``None`` when unknown / large enough to ignore.
    max_request_tokens: int | None = None
    #: Whether a pinned model id (tier routing) means anything on this provider.
    accepts_pinned_model: bool = True


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One provider call, for cost and latency accounting. Never contains message text."""

    provider: str
    model: str
    ok: bool
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    status_code: int | None = None
    failure_kind: str | None = None
    used_effort: bool = False
    tier: str | None = None


UsageSink = Callable[[UsageRecord], None]


@dataclass(frozen=True, slots=True)
class LLMResult:
    completion: ChatCompletion
    provider: str
    model: str
    attempts: tuple[Attempt, ...] = ()  # failures that happened before the answer


def classify_error(exc: BaseException) -> tuple[FailureKind, int | None]:
    """Map an exception from the OpenAI SDK to a failure kind and an HTTP status."""
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        if status in (401, 403):
            return "auth", status
        if status == 402:
            return "payment", status
        if status == 429:
            return "rate_limit", status
        if status == 413:
            return "too_large", status
        if status >= 500:
            return "server", status
        if 400 <= status < 500:
            return "bad_request", status
        return "other", status
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return "network", None
    return "other", None


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def estimate_tokens(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None,
    chars_per_token: float,
) -> int:
    """Cheap token estimate: serialized size divided by ``chars_per_token`` (3.5 by default)."""
    chars = len(json.dumps(messages, ensure_ascii=False, default=str))
    if tools:
        chars += len(json.dumps(tools, ensure_ascii=False, default=str))
    return int(chars / chars_per_token) + 1


@dataclass(frozen=True, slots=True)
class _Outcome:
    completion: Any | None
    failure: Attempt | None = None
    error: BaseException | None = None


@dataclass
class _Cooldowns:
    clock: Callable[[], float]
    until: dict[tuple[str, str], float] = field(default_factory=dict)

    def remaining(self, provider: str, model: str) -> float:
        return max(0.0, self.until.get((provider, model), 0.0) - self.clock())

    def rest(self, provider: str, model: str, seconds: float) -> None:
        self.until[(provider, model)] = self.clock() + seconds

    def clear(self, provider: str, model: str) -> None:
        self.until.pop((provider, model), None)


class LLMChain:
    """Calls chat completions through an ordered list of providers."""

    def __init__(
        self,
        providers: Sequence[ProviderSpec],
        config: AIConfig,
        *,
        usage_sink: UsageSink | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._providers = tuple(providers)
        self._config = config
        self._usage_sink = usage_sink
        self._cooldowns = _Cooldowns(clock)
        self._clock = clock

    @property
    def providers(self) -> tuple[ProviderSpec, ...]:
        return self._providers

    def tier_model(self, tier: str) -> str:
        """Model id for a tier (``small`` or ``large``), from configuration."""
        if tier == "small":
            return self._config.groq_model_small
        if tier == "large":
            return self._config.groq_model_large
        raise ValueError(f"unknown tier {tier!r}")

    def is_resting(self, provider: str, model: str) -> bool:
        return self._cooldowns.remaining(provider, model) > 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        model: str | None = None,
        tier: str | None = None,
        effort: str | None = None,
    ) -> LLMResult:
        """Return the first answer in the chain.

        ``model`` or ``tier`` pins a single candidate per provider (``model`` wins).
        Raises :class:`NoProviderConfigured`, :class:`RequestTooLarge` or
        :class:`AllProvidersFailed`.
        """
        if not self._providers:
            raise NoProviderConfigured("no LLM provider has an API key")
        pinned = model or (self.tier_model(tier) if tier else None)
        estimated = estimate_tokens(messages, tools, self._config.est_chars_per_token)

        candidates: list[tuple[ProviderSpec, str]] = []
        attempts: list[Attempt] = []
        skipped_too_large = 0
        for spec in self._providers:
            if pinned and not spec.accepts_pinned_model:
                continue
            for name in [pinned] if pinned else spec.models:
                if (
                    spec.max_request_tokens is not None
                    and estimated > spec.max_request_tokens
                ):
                    skipped_too_large += 1
                    attempts.append(
                        Attempt(
                            spec.name,
                            name,
                            "too_large",
                            None,
                            f"estimated {estimated} tokens over wall {spec.max_request_tokens}",
                        )
                    )
                    continue
                candidates.append((spec, name))
        if not candidates:
            if skipped_too_large:
                raise RequestTooLarge(estimated, tuple(attempts))
            raise NoProviderConfigured("no provider can serve the requested model")

        ready = [c for c in candidates if not self.is_resting(c[0].name, c[1])]
        resting = sorted(
            (c for c in candidates if self.is_resting(c[0].name, c[1])),
            key=lambda c: self._cooldowns.remaining(c[0].name, c[1]),
        )
        last_exc: BaseException | None = None
        for spec, name in ready + resting:
            if self.is_resting(spec.name, name):
                attempts.append(
                    Attempt(
                        spec.name, name, "cooldown", None, "resting; last-chance try"
                    )
                )
            outcome = await self._try_candidate(
                spec, name, messages, tools, effort, tier
            )
            if outcome.completion is not None:
                return LLMResult(outcome.completion, spec.name, name, tuple(attempts))
            assert outcome.failure is not None
            attempts.append(outcome.failure)
            last_exc = outcome.error
        raise AllProvidersFailed(tuple(attempts)) from last_exc

    async def _try_candidate(
        self,
        spec: ProviderSpec,
        name: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None,
        effort: str | None,
        tier: str | None,
    ) -> _Outcome:
        payload: dict[str, Any] = {
            "model": name,
            "messages": list(messages),
            "tools": list(tools) if tools else None,
        }
        variants = (
            [{**payload, "reasoning_effort": effort}, payload] if effort else [payload]
        )
        failure: _Outcome | None = None
        for variant in variants:
            started = self._clock()
            try:
                completion = await spec.client.chat.completions.create(**variant)
            except openai.APIError as exc:
                kind, status = classify_error(exc)
                self._report(
                    spec.name,
                    name,
                    started,
                    ok=False,
                    status=status,
                    kind=kind,
                    used_effort="reasoning_effort" in variant,
                    tier=tier,
                )
                failure = _Outcome(
                    None, Attempt(spec.name, name, kind, status, _short(exc)), exc
                )
                if "reasoning_effort" in variant and status == 400:
                    logger.warning(
                        "%s/%s rejected reasoning_effort; retrying without it",
                        spec.name,
                        name,
                    )
                    continue
                self._maybe_rest(spec.name, name, kind, exc)
                logger.warning(
                    "%s/%s failed (%s %s); next candidate",
                    spec.name,
                    name,
                    kind,
                    status,
                )
                return failure
            self._report(
                spec.name,
                name,
                started,
                ok=True,
                completion=completion,
                used_effort="reasoning_effort" in variant,
                tier=tier,
            )
            self._cooldowns.clear(spec.name, name)
            return _Outcome(completion)
        assert failure is not None
        return failure

    def _maybe_rest(
        self, provider: str, model: str, kind: str, exc: BaseException
    ) -> None:
        if kind not in COOLDOWN_KINDS:
            return
        seconds = self._config.provider_cooldown_seconds
        hinted = _retry_after_seconds(exc)
        if hinted is not None:
            seconds = min(max(hinted, 1.0), self._config.provider_cooldown_max_seconds)
        self._cooldowns.rest(provider, model, seconds)

    def _report(
        self,
        provider: str,
        model: str,
        started: float,
        *,
        ok: bool,
        status: int | None = None,
        kind: str | None = None,
        completion: ChatCompletion | None = None,
        used_effort: bool = False,
        tier: str | None = None,
    ) -> None:
        if self._usage_sink is None:
            return
        usage = getattr(completion, "usage", None)
        record = UsageRecord(
            provider=provider,
            model=model,
            ok=ok,
            latency_ms=int((self._clock() - started) * 1000),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            status_code=status,
            failure_kind=kind,
            used_effort=used_effort,
            tier=tier,
        )
        try:
            self._usage_sink(record)
        except Exception:
            logger.exception("usage sink failed")


def _short(exc: BaseException) -> str:
    return str(exc)[:300]
