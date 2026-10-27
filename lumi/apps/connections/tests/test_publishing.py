from __future__ import annotations

import asyncio

import httpx
import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.errors import (
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    ValidationFailed,
)
from apps.connections.providers.base import AccountInfo, PublishDraft, TokenSet
from apps.connections.providers.registry import build_provider
from apps.connections.publishing import (
    ConfirmationRequired,
    IdempotencyConflict,
    Publisher,
    PublishInProgress,
)

from .fakes import MemoryLedger, Recorder

TOKENS = TokenSet(access_token="li-access-FAKE", scopes=("w_member_social",))
ACCOUNT = AccountInfo(external_id="782bbtaQ", display_name="Christian")
CONFIG = ConnectionsConfig.from_env({})


def setup(handler):
    rec = Recorder(handler)
    provider = build_provider("linkedin", CONFIG, transport=rec.transport)
    ledger = MemoryLedger()
    return provider, Publisher(ledger), ledger, rec


def created(request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})


async def publish(publisher, provider, text="hola", **kwargs):
    kwargs.setdefault("confirm", True)
    kwargs.setdefault("idempotency_key", "k1")
    return await publisher.publish(
        provider, TOKENS, ACCOUNT, PublishDraft(text=text), user_id=1, **kwargs
    )


async def test_publish_without_confirm_sends_nothing() -> None:
    provider, publisher, ledger, rec = setup(created)
    for flag in (False, "true", 1):
        with pytest.raises(ConfirmationRequired):
            await publish(publisher, provider, confirm=flag)
    assert rec.requests == [] and ledger.entries == {}


async def test_missing_or_oversized_key_is_refused() -> None:
    provider, publisher, _, rec = setup(created)
    for key in (None, "", "   ", "k" * 129):
        with pytest.raises(ValidationFailed):
            await publish(publisher, provider, idempotency_key=key)
    assert rec.requests == []


async def test_dry_run_needs_no_confirmation_and_leaves_no_trace() -> None:
    provider, publisher, ledger, rec = setup(created)
    done = await publish(
        publisher, provider, confirm=False, idempotency_key=None, dry_run=True
    )
    assert done.result.dry_run and not done.replayed
    assert rec.requests == [] and ledger.entries == {}


async def test_same_key_replays_the_stored_result_and_posts_once() -> None:
    provider, publisher, _, rec = setup(created)
    first = await publish(publisher, provider)
    second = await publish(publisher, provider)
    assert first.replayed is False and second.replayed is True
    assert second.result.external_post_id == "urn:li:share:1"
    assert len(rec.requests) == 1


async def test_concurrent_double_click_posts_once() -> None:
    provider, publisher, _, rec = setup(created)
    results = await asyncio.gather(
        publish(publisher, provider),
        publish(publisher, provider),
        return_exceptions=True,
    )
    posted = [r for r in results if not isinstance(r, Exception) and not r.replayed]
    assert len(posted) == 1 and len(rec.requests) == 1


async def test_same_key_with_another_draft_is_a_conflict() -> None:
    provider, publisher, _, rec = setup(created)
    await publish(publisher, provider, text="uno")
    with pytest.raises(IdempotencyConflict):
        await publish(publisher, provider, text="dos")
    assert len(rec.requests) == 1


async def test_invalid_draft_never_occupies_a_key() -> None:
    provider, publisher, ledger, rec = setup(created)
    with pytest.raises(ValidationFailed):
        await publish(publisher, provider, text=" ")
    assert ledger.entries == {} and rec.requests == []


async def test_definite_failure_allows_retry_with_the_same_key() -> None:
    answers = iter(
        [
            httpx.Response(401),
            httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"}),
        ]
    )
    provider, publisher, ledger, rec = setup(lambda r: next(answers))
    with pytest.raises(ProviderAuthError):
        await publish(publisher, provider)
    assert ledger.log[-1] == ("k1", "failed")
    retried = await publish(publisher, provider)
    assert retried.result.external_post_id == "urn:li:share:9" and not retried.replayed
    assert len(rec.requests) == 2


async def test_ambiguous_failure_is_parked_and_not_retried_blindly() -> None:
    provider, publisher, ledger, rec = setup(lambda r: httpx.Response(503))
    with pytest.raises(ProviderUnavailable):
        await publish(publisher, provider)
    assert ledger.log[-1] == ("k1", "unknown")
    with pytest.raises(PublishInProgress):
        await publish(publisher, provider)
    assert len(rec.requests) == 1


async def test_cancellation_mid_publish_is_parked_as_unknown() -> None:
    started = asyncio.Event()

    async def hang(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(60)
        return httpx.Response(201)

    rec = Recorder(None)
    rec.transport = httpx.MockTransport(hang)
    provider = build_provider("linkedin", CONFIG, transport=rec.transport)
    ledger = MemoryLedger()
    task = asyncio.create_task(publish(Publisher(ledger), provider))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ledger.log[-1] == ("k1", "unknown")


async def test_x_off_publish_is_refused_and_parks_nothing_as_unknown() -> None:
    rec = Recorder(lambda r: pytest.fail("no request expected"))
    config = ConnectionsConfig.from_env({"X_CLIENT_ID": "i", "X_CLIENT_SECRET": "s"})
    provider = build_provider("x", config, transport=rec.transport)
    ledger = MemoryLedger()
    tokens = TokenSet(access_token="a", scopes=("tweet.write",))
    with pytest.raises(LiveDisabled):
        await Publisher(ledger).publish(
            provider,
            tokens,
            ACCOUNT,
            PublishDraft(text="hola"),
            user_id=1,
            confirm=True,
            idempotency_key="k",
        )
    assert rec.requests == [] and ledger.log == [("k", "failed")]
