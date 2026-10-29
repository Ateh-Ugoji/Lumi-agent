"""Shared async HTTP client for providers.

* The transport is injectable, so tests pass ``httpx.MockTransport`` and no socket opens.
* Every request is checked against the provider's allowed hosts before it is sent.
* Error mapping is central: 401/403 -> ``ProviderAuthError``, 402 -> ``BudgetExceeded``,
  429 -> ``RateLimited``, 5xx and network errors -> ``ProviderUnavailable``, other 4xx ->
  ``ProviderRequestError``.
* Error messages never contain URLs (Meta puts secrets in query strings), headers or bodies,
  only a short provider message taken from known fields.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from .errors import (
    BudgetExceeded,
    ProviderAuthError,
    ProviderRequestError,
    ProviderUnavailable,
    RateLimited,
)

DEFAULT_TIMEOUT = 15.0
MAX_RETRY_AFTER = 30.0
_MESSAGE_FIELDS = ("error_description", "detail", "title", "message", "error")

Sleep = Callable[[float], Awaitable[None]]
# Meta signals auth and throttling inside a 4xx body, by error code.
_META_AUTH_CODES = {102, 190}
_META_RATE_CODES = {4, 17, 32, 341, 613}
# RFC 6749 token endpoint errors that mean the credential or grant is no longer valid.
_OAUTH_AUTH_ERRORS = {
    "invalid_grant",
    "invalid_token",
    "invalid_client",
    "unauthorized_client",
}


class HostNotAllowed(ProviderRequestError):
    """A request targeted a host outside the provider's allow-list. Nothing was sent."""


def short_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            body = error
        for name in _MESSAGE_FIELDS:
            value = body.get(name)
            if isinstance(value, str) and value:
                return value[:200]
    return f"HTTP {response.status_code}"


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code") is not None:
            return str(error["code"])
        if isinstance(error, str):
            return error
    return None


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def raise_for_provider(response: httpx.Response, provider: str) -> None:
    """Map a non-2xx response to a typed error. Returns for 2xx."""
    status = response.status_code
    if status < 300:
        return
    if status < 400:
        # Redirects are never followed, so a 3xx is not a usable answer.
        raise ProviderRequestError(
            "unexpected redirect", provider=provider, status=status
        )
    message = short_message(response)
    code = _error_code(response)
    if code is not None and code.isdigit():
        if int(code) in _META_AUTH_CODES:
            raise ProviderAuthError(message, provider=provider)
        if int(code) in _META_RATE_CODES:
            raise RateLimited(
                message, provider=provider, retry_after_seconds=_retry_after(response)
            )
    if code in _OAUTH_AUTH_ERRORS or status in (401, 403):
        raise ProviderAuthError(message, provider=provider)
    if status == 402:
        raise BudgetExceeded(message, provider=provider)
    if status == 429:
        raise RateLimited(
            message, provider=provider, retry_after_seconds=_retry_after(response)
        )
    if status >= 500:
        raise ProviderUnavailable(message, provider=provider)
    raise ProviderRequestError(message, provider=provider, status=status, code=code)


class ProviderHttp:
    def __init__(
        self,
        provider: str,
        *,
        allowed_hosts: frozenset[str],
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.provider = provider
        self._hosts = allowed_hosts
        self._transport = transport
        self._timeout = timeout
        self._sleep = sleep

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        retries: int = 0,
        check: bool = True,
    ) -> httpx.Response:
        """Send one request. ``retries`` applies to 429 and 5xx, and to network errors.

        Callers that are not idempotent (publishing) pass ``retries=0``.
        """
        host = httpx.URL(url).host
        if host not in self._hosts:
            raise HostNotAllowed(
                f"host not allowed for {self.provider}", provider=self.provider
            )
        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as client:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        data=data,
                        json=json,
                        headers=headers,
                        auth=auth,
                    )
            except httpx.HTTPError as exc:
                if attempt < retries:
                    attempt += 1
                    await self._sleep(min(2.0**attempt * 0.2, MAX_RETRY_AFTER))
                    continue
                raise ProviderUnavailable(
                    f"network error: {type(exc).__name__}", provider=self.provider
                ) from None
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < retries:
                attempt += 1
                wait = _retry_after(response)
                await self._sleep(
                    min(
                        wait if wait is not None else 2.0**attempt * 0.2,
                        MAX_RETRY_AFTER,
                    )
                )
                continue
            if check:
                raise_for_provider(response, self.provider)
            return response
