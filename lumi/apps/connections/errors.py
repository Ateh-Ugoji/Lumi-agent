"""Typed errors of the connections layer.

The five contract errors are defined in ``lumi_ai.ports`` and re-exported here, so a caller
catches the same class whether it comes from a provider or from ``SocialData``.
"""

from __future__ import annotations

from lumi_ai.ports import (
    BudgetExceeded,
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    RateLimited,
    SocialDataError,
    UnsupportedPlatform,
)

__all__ = [
    "BudgetExceeded",
    "ConfigError",
    "LiveDisabled",
    "OAuthStateError",
    "ProviderAuthError",
    "ProviderRequestError",
    "ProviderUnavailable",
    "RateLimited",
    "SocialDataError",
    "UnsupportedOperation",
    "UnsupportedPlatform",
    "ValidationFailed",
]


class ConfigError(Exception):
    """A required setting is missing or malformed. The message never contains a secret."""


class ProviderRequestError(SocialDataError):
    """The provider rejected the request for a reason that is not auth, rate limit or outage."""

    def __init__(
        self,
        message: str = "",
        *,
        provider: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.status = status
        self.code = code


class UnsupportedOperation(SocialDataError):
    """The provider has no way to do this operation (for example refresh on LinkedIn)."""


class ValidationFailed(SocialDataError):
    """A draft cannot be published as given (empty, too long, missing confirmation)."""


class OAuthStateError(Exception):
    """The OAuth ``state`` is unknown, already used or expired. ``code`` is machine readable."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
