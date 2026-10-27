"""Typed errors of the LLM provider chain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FailureKind = Literal[
    "auth",  # 401/403: key rejected or missing scope
    "payment",  # 402: empty balance
    "rate_limit",  # 429
    "too_large",  # 413, or a local pre-check against the provider's token wall
    "bad_request",  # 400/404/422 and other 4xx that are not about the account
    "server",  # 5xx
    "network",  # connection error or timeout
    "other",
]

# Kinds after which the same candidate is not worth trying on the next turn.
COOLDOWN_KINDS: frozenset[str] = frozenset({"auth", "payment", "rate_limit"})


@dataclass(frozen=True, slots=True)
class Attempt:
    """One failed (or skipped) try, kept so the final error can say what happened."""

    provider: str
    model: str
    kind: FailureKind | Literal["cooldown"]
    status_code: int | None
    message: str


class LLMError(RuntimeError):
    """Base class of every error raised by the provider chain."""


class NoProviderConfigured(LLMError):
    """No provider has an API key, so there is nothing to call."""


class RequestTooLarge(LLMError):
    """The request is over every candidate's token wall. The caller must trim and retry."""

    def __init__(
        self, estimated_tokens: int, attempts: tuple[Attempt, ...] = ()
    ) -> None:
        super().__init__(
            f"request of ~{estimated_tokens} tokens exceeds every provider limit"
        )
        self.estimated_tokens = estimated_tokens
        self.attempts = attempts


class AllProvidersFailed(LLMError):
    """Every candidate failed. ``attempts`` lists them in order; ``__cause__`` is the last error."""

    def __init__(self, attempts: tuple[Attempt, ...]) -> None:
        summary = "; ".join(
            f"{a.provider}/{a.model}: {a.kind}{f' {a.status_code}' if a.status_code else ''}"
            for a in attempts
        )
        super().__init__(f"all LLM providers failed ({summary})")
        self.attempts = attempts

    @property
    def last_status(self) -> int | None:
        for a in reversed(self.attempts):
            if a.status_code is not None:
                return a.status_code
        return None
