"""OAuth 2.0 helpers and the state flow.

The ``state`` is stored through ``OAuthStateStore``. Django's implementation (model
``OAuthState``, T3) must make ``consume`` atomic, for example with a single
``UPDATE ... WHERE consumed_at IS NULL`` so two callbacks cannot both win. Process memory is
never an acceptable store: workers are many and restarts are normal.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

from .config import ConnectionsConfig
from .errors import OAuthStateError
from .providers.base import AuthorizationRequest, SocialProvider, TokenSet

STATE_TTL = timedelta(minutes=10)
MAX_STATE_LENGTH = 256
Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    # RFC 7636: 43 to 128 characters. 64 random bytes give 86.
    return secrets.token_urlsafe(64)


def code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(slots=True)
class OAuthStateRecord:
    state: str = field(repr=False)
    provider: str
    user_id: int | str
    redirect_uri: str
    redirect_after: str
    expires_at: datetime
    code_verifier: str | None = field(default=None, repr=False)


class OAuthStateStore(Protocol):
    async def save(self, record: OAuthStateRecord) -> None: ...

    async def consume(self, state: str, provider: str) -> OAuthStateRecord | None:
        """Return the record and mark it used, atomically. ``None`` if unknown or used."""
        ...


def _has_unsafe_chars(value: str) -> bool:
    # Browsers drop tabs and newlines inside URLs, so "/\t/evil.com" turns into "//evil.com".
    return any(ord(c) < 0x21 or ord(c) == 0x7F for c in value)


def safe_redirect_after(target: str | None, frontend_url: str) -> str:
    """Return a post-login destination that stays on the frontend.

    Accepts a relative path or a URL on the same origin as ``FRONTEND_URL``. Anything else
    falls back to ``/`` so the callback cannot be used as an open redirect.
    """
    if not target or _has_unsafe_chars(target):
        return "/"
    if (
        target.startswith("/")
        and not target.startswith(("//", "/\\"))
        and "\\" not in target
    ):
        return target
    parts, front = urlsplit(target), urlsplit(frontend_url)
    if (parts.scheme, parts.netloc) == (
        front.scheme,
        front.netloc,
    ) and "\\" not in target:
        return target
    return "/"


@dataclass(frozen=True, slots=True)
class CompletedAuth:
    record: OAuthStateRecord
    tokens: TokenSet


class OAuthFlow:
    def __init__(
        self,
        provider: SocialProvider,
        store: OAuthStateStore,
        config: ConnectionsConfig,
        *,
        clock: Clock = utcnow,
    ) -> None:
        self._provider = provider
        self._store = store
        self._config = config
        self._clock = clock

    async def start(
        self, user_id: int | str, redirect_after: str | None = None
    ) -> AuthorizationRequest:
        name = self._provider.name
        redirect_uri = self._config.redirect_uri(name)
        state = new_state()
        verifier = (
            new_code_verifier() if self._provider.capabilities().uses_pkce else None
        )
        request = self._provider.build_authorize_url(
            state=state,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge_s256(verifier) if verifier else None,
        )
        await self._store.save(
            OAuthStateRecord(
                state=state,
                provider=name,
                user_id=user_id,
                redirect_uri=redirect_uri,
                redirect_after=safe_redirect_after(
                    redirect_after, self._config.frontend_url
                ),
                expires_at=self._clock() + STATE_TTL,
                code_verifier=verifier,
            )
        )
        return request

    async def complete(
        self, *, state: str, code: str, expected_user_id: int | str | None = None
    ) -> CompletedAuth:
        """Finish the callback.

        Pass ``expected_user_id`` (the logged-in user) so a state started by someone else cannot
        attach its account to this session. The state is consumed first, so a failed exchange
        burns it and the user must start again.
        """
        if not state or len(state) > MAX_STATE_LENGTH:
            raise OAuthStateError("state_invalid")
        record = await self._store.consume(state, self._provider.name)
        if record is None:
            raise OAuthStateError("state_invalid")
        if expected_user_id is not None and str(record.user_id) != str(
            expected_user_id
        ):
            raise OAuthStateError("state_invalid")
        if record.expires_at <= self._clock():
            raise OAuthStateError("state_expired")
        tokens = await self._provider.exchange_code(
            code=code,
            redirect_uri=record.redirect_uri,
            code_verifier=record.code_verifier,
        )
        return CompletedAuth(record=record, tokens=tokens)
