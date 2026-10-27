"""Publishing with explicit confirmation and idempotency.

Rules enforced here, not left to each provider:

* A real publish needs ``confirm=True``. The agent never publishes on its own.
* A real publish needs an idempotency key. Repeating the same key with the same draft returns the
  stored result and sends nothing. The same key with a different draft is refused.
* A dry run touches no ledger and no network beyond what the provider needs to validate. It
  does not need confirmation.
* If a publish ends in an ambiguous failure (timeout, 5xx), the post may exist. The key is
  parked as ``unknown`` and is not retried automatically.

``scope`` is the owner of the idempotency key. SCHEMA.md makes ``publish_jobs`` unique on
(``profile``, ``idempotency_key``), so Django passes the profile id.

Django's ``PublishLedger`` implementation (T3) must make ``begin`` atomic, for example an
``INSERT ... ON CONFLICT DO NOTHING`` on a unique ``(scope, key)``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol

from .errors import (
    ProviderUnavailable,
    SocialDataError,
    ValidationFailed,
)
from .providers.base import (
    AccountInfo,
    PublishDraft,
    PublishResult,
    SocialProvider,
    TokenSet,
)

LedgerStatus = Literal["pending", "done", "failed", "unknown"]
MAX_KEY_LENGTH = 128


class ConfirmationRequired(ValidationFailed):
    """The call did not carry ``confirm=True``."""


class IdempotencyConflict(ValidationFailed):
    """The key was already used for a different draft or account."""


class PublishInProgress(SocialDataError):
    """The key is pending or its outcome is unknown. Check the platform before retrying."""


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    key: str
    fingerprint: str
    status: LedgerStatus
    result: PublishResult | None = None


class PublishLedger(Protocol):
    async def begin(
        self, scope: int | str, key: str, fingerprint: str
    ) -> tuple[LedgerEntry, bool]:
        """Insert a ``pending`` entry, or return the existing one. The bool is ``created``."""
        ...

    async def restart(self, scope: int | str, key: str) -> None:
        """Move a ``failed`` entry back to ``pending``, atomically."""
        ...

    async def finish(
        self,
        scope: int | str,
        key: str,
        status: LedgerStatus,
        result: PublishResult | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class Published:
    result: PublishResult
    replayed: bool


def fingerprint(provider: str, account: AccountInfo, draft: PublishDraft) -> str:
    raw = "\x1f".join([provider, account.external_id, draft.text, draft.link or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Publisher:
    def __init__(self, ledger: PublishLedger) -> None:
        self._ledger = ledger

    async def publish(
        self,
        provider: SocialProvider,
        tokens: TokenSet,
        account: AccountInfo,
        draft: PublishDraft,
        *,
        scope: int | str,
        confirm: bool = False,
        idempotency_key: str | None = None,
        dry_run: bool = False,
    ) -> Published:
        if dry_run:
            result = await provider.publish(tokens, account, draft, dry_run=True)
            return Published(result=result, replayed=False)
        if confirm is not True:
            raise ConfirmationRequired(
                "publishing needs confirm=true", provider=provider.name
            )
        key = (idempotency_key or "").strip()
        if not key or len(key) > MAX_KEY_LENGTH:
            raise ValidationFailed(
                f"an idempotency key of 1 to {MAX_KEY_LENGTH} characters is required",
                provider=provider.name,
            )
        # Validate first so a bad draft never occupies a key.
        await provider.publish(tokens, account, draft, dry_run=True)

        fp = fingerprint(provider.name, account, draft)
        entry, created = await self._ledger.begin(scope, key, fp)
        if not created:
            if entry.fingerprint != fp:
                raise IdempotencyConflict(
                    "this idempotency key was used for a different post",
                    provider=provider.name,
                )
            if entry.status == "done" and entry.result is not None:
                return Published(result=entry.result, replayed=True)
            if entry.status == "failed":
                await self._ledger.restart(scope, key)
            else:
                raise PublishInProgress(
                    "this post is pending or its outcome is unknown; check the platform",
                    provider=provider.name,
                )
        try:
            result = await provider.publish(tokens, account, draft, dry_run=False)
        except ProviderUnavailable:
            await self._ledger.finish(scope, key, "unknown")
            raise
        except SocialDataError:
            # Typed refusals (auth, rate limit, validation, live switch) mean nothing was posted.
            await self._ledger.finish(scope, key, "failed")
            raise
        except BaseException:
            # A bug or a cancelled task: the request may have gone out.
            await self._ledger.finish(scope, key, "unknown")
            raise
        await self._ledger.finish(scope, key, "done", result)
        return Published(result=result, replayed=False)
