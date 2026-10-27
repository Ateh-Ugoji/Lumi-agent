from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.errors import OAuthStateError
from apps.connections.oauth import (
    OAuthFlow,
    code_challenge_s256,
    new_code_verifier,
    new_state,
    safe_redirect_after,
)
from apps.connections.providers.registry import build_provider

from .fakes import MemoryStateStore, Recorder, json_response, routes

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
CONFIG = ConnectionsConfig.from_env(
    {
        "META_APP_ID": "app-1",
        "META_APP_SECRET": "sec-1",
        "X_CLIENT_ID": "x-id",
        "X_CLIENT_SECRET": "x-sec",
        "X_LIVE_ENABLED": "true",
    }
)


def test_pkce_challenge_matches_rfc7636_vector() -> None:
    # Appendix B of RFC 7636.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert (
        code_challenge_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_verifier_and_state_are_long_unique_and_url_safe() -> None:
    verifier = new_code_verifier()
    assert 43 <= len(verifier) <= 128
    assert new_state() != new_state()
    assert len(new_state()) >= 32
    raw = base64.urlsafe_b64decode(code_challenge_s256(verifier) + "=")
    assert raw == hashlib.sha256(verifier.encode()).digest()


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example.org/",
        "//evil.example.org/",
        "/\\evil.example.org",
        "javascript:alert(1)",
        "https://localhost:3010.evil.org/",
        "http://localhost:3011/",
        "/\t/evil.example.org",
        "/\n/evil.example.org",
        "/ /evil.example.org",
        "http://localhost:3010/\r\nSet-Cookie: x=1",
        "",
        None,
    ],
)
def test_redirect_after_never_leaves_the_frontend(target: str | None) -> None:
    assert safe_redirect_after(target, "http://localhost:3010") == "/"


@pytest.mark.parametrize(
    "target", ["/settings", "/settings?x=1", "http://localhost:3010/settings"]
)
def test_redirect_after_keeps_frontend_targets(target: str) -> None:
    assert safe_redirect_after(target, "http://localhost:3010") == target


def flow(
    name: str, store: MemoryStateStore, handler=None, clock=lambda: NOW
) -> tuple[OAuthFlow, Recorder]:
    rec = Recorder(handler or (lambda r: httpx.Response(500)))
    provider = build_provider(name, CONFIG, transport=rec.transport, clock=clock)
    return OAuthFlow(provider, store, CONFIG, clock=clock), rec


async def test_start_stores_state_and_pkce_for_x_and_returns_matching_url() -> None:
    store = MemoryStateStore()
    oauth, rec = flow("x", store)
    request = await oauth.start(user_id=7, redirect_after="/settings")
    query = parse_qs(urlsplit(request.url).query)
    record = store.records[request.state]
    assert query["state"] == [request.state]
    assert query["code_challenge"] == [code_challenge_s256(record.code_verifier)]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://localhost:3010/connections/x/callback"]
    assert record.user_id == 7 and record.redirect_after == "/settings"
    assert record.expires_at == NOW + timedelta(minutes=10)
    assert rec.requests == []


async def test_start_for_meta_has_no_pkce() -> None:
    store = MemoryStateStore()
    oauth, _ = flow("meta", store)
    request = await oauth.start(user_id=1)
    assert store.records[request.state].code_verifier is None
    assert "code_challenge" not in request.url


async def test_complete_exchanges_the_code_and_state_is_single_use() -> None:
    store = MemoryStateStore()
    handler = routes(
        {
            ("POST", "/v26.0/oauth/access_token"): lambda r: json_response(
                "meta_long_token.json"
                if httpx.QueryParams(r.content.decode()).get("grant_type")
                else "meta_short_token.json"
            ),
        }
    )
    oauth, _ = flow("meta", store, handler)
    request = await oauth.start(user_id=1)
    done = await oauth.complete(state=request.state, code="abc")
    assert done.tokens.access_token == "meta-long-FAKE"
    assert done.record.user_id == 1
    with pytest.raises(OAuthStateError) as info:
        await oauth.complete(state=request.state, code="abc")  # replay
    assert info.value.code == "state_invalid"


async def test_unknown_state_is_rejected_before_any_request() -> None:
    oauth, rec = flow("meta", MemoryStateStore())
    with pytest.raises(OAuthStateError):
        await oauth.complete(state="forged", code="abc")
    assert rec.requests == []


async def test_state_of_another_provider_is_rejected() -> None:
    store = MemoryStateStore()
    meta_flow, _ = flow("meta", store)
    li_flow, rec = flow("x", store)
    request = await meta_flow.start(user_id=1)
    with pytest.raises(OAuthStateError):
        await li_flow.complete(state=request.state, code="abc")
    assert rec.requests == []


async def test_expired_state_is_rejected_without_exchange() -> None:
    store = MemoryStateStore()
    now = [NOW]
    oauth, rec = flow("meta", store, clock=lambda: now[0])
    request = await oauth.start(user_id=1)
    now[0] = NOW + timedelta(minutes=11)
    with pytest.raises(OAuthStateError) as info:
        await oauth.complete(state=request.state, code="abc")
    assert info.value.code == "state_expired"
    assert rec.requests == []


async def test_callback_for_another_user_is_rejected() -> None:
    store = MemoryStateStore()
    oauth, rec = flow("meta", store)
    request = await oauth.start(user_id=1)
    with pytest.raises(OAuthStateError) as info:
        await oauth.complete(state=request.state, code="abc", expected_user_id=2)
    assert info.value.code == "state_mismatch" and rec.requests == []
    assert request.state in store.records  # refused without being consumed


class _StoreThatIgnoresTheUser(MemoryStateStore):
    """A buggy store: it hands the record back whoever asks."""

    async def consume(self, state, provider, *, user_id=None):
        return await super().consume(state, provider, user_id=None)


async def test_the_flow_refuses_a_foreign_state_even_if_the_store_does_not() -> None:
    store = _StoreThatIgnoresTheUser()
    oauth, rec = flow("meta", store)
    request = await oauth.start(user_id=1)
    with pytest.raises(OAuthStateError) as info:
        await oauth.complete(state=request.state, code="abc", expected_user_id=2)
    assert info.value.code == "state_mismatch"
    assert rec.requests == []  # the code was never exchanged


@pytest.mark.parametrize("state", ["", "x" * 257])
async def test_malformed_state_never_reaches_the_store(state: str) -> None:
    store = MemoryStateStore()
    oauth, rec = flow("meta", store)
    with pytest.raises(OAuthStateError):
        await oauth.complete(state=state, code="abc")
    assert rec.requests == []


async def test_failed_exchange_burns_the_state() -> None:
    store = MemoryStateStore()
    oauth, _ = flow(
        "meta",
        store,
        lambda r: httpx.Response(400, json={"error": {"code": 100, "message": "bad"}}),
    )
    request = await oauth.start(user_id=1)
    with pytest.raises(Exception):  # noqa: B017 - any typed provider error
        await oauth.complete(state=request.state, code="abc")
    with pytest.raises(OAuthStateError):
        await oauth.complete(state=request.state, code="abc")
