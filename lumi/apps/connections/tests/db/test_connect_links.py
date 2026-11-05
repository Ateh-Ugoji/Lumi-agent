# ruff: noqa: F811
"""``ConnectionLinks`` over the real database, with mocked providers and no network."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from asgiref.sync import async_to_sync

from apps.connections import accounts
from apps.connections.connect_links import DjangoConnectionLinks
from apps.connections.models import ConnectedAccount, OAuthState
from apps.connections.tests.db.test_api import (  # noqa: F401  (fixtures)
    META_ENV,
    PFM_ENV,
    X_ENV,
    env,
    providers,
    wiring,
)
from apps.connections.tests.fakes import json_response
from lumi_ai import cancel
from lumi_ai.ports import (
    ConnectionLinks,
    LiveDisabled,
    ProviderUnavailable,
    UnsupportedPlatform,
)

pytestmark = pytest.mark.django_db


def start(profile_id: int, platform: str, handle: str | None = None):
    return async_to_sync(DjangoConnectionLinks().start_connect)(
        profile_id, platform, handle
    )


def test_it_satisfies_the_port() -> None:
    assert isinstance(DjangoConnectionLinks(), ConnectionLinks)


def test_facebook_mints_a_meta_link_and_stores_the_state(env, profile) -> None:
    env(META_ENV)
    link = start(profile.pk, "facebook", "mypage")
    assert not link.already_connected and link.handle == "mypage"
    assert urlsplit(link.url).netloc == "www.facebook.com"
    row = OAuthState.objects.get()
    assert row.provider == "meta" and row.social_profile_id == profile.pk


def test_an_active_account_of_that_platform_is_reported_not_relinked(
    env, profile, user
) -> None:
    env(META_ENV)
    ConnectedAccount.objects.create(
        user=user,
        provider="meta",
        external_account_id="p1",
        platform="facebook",
        handle="mypage",
        access_token="t",
    )
    link = start(profile.pk, "facebook")
    assert link.already_connected and link.url is None and link.handle == "mypage"
    assert OAuthState.objects.count() == 0


def test_instagram_goes_through_post_for_me(env, providers, profile) -> None:
    env(PFM_ENV)
    providers.on(
        "pfm",
        {("POST", "/v1/social-accounts/auth-url"): json_response("pfm_auth_url.json")},
    )
    link = start(profile.pk, "instagram")
    assert link.url and not link.already_connected
    assert OAuthState.objects.count() == 0  # PFM keeps the state itself


def test_x_without_its_switch_falls_back_to_pfm_or_says_why(env, profile) -> None:
    env(X_ENV)
    with pytest.raises(UnsupportedPlatform):
        start(profile.pk, "x")
    assert OAuthState.objects.count() == 0


def test_a_platform_with_no_configured_provider_is_unsupported(profile) -> None:
    with pytest.raises(UnsupportedPlatform):
        start(profile.pk, "tiktok")


def test_x_live_disabled_with_a_provider_error_is_typed(
    env, profile, monkeypatch
) -> None:
    env(X_ENV)
    monkeypatch.setenv("X_LIVE_ENABLED", "true")
    monkeypatch.setattr(
        accounts,
        "start_connect",
        lambda *a, **k: (_ for _ in ()).throw(
            accounts.ApiError("connections.live_disabled", "off", status_code=409)
        ),
    )
    with pytest.raises(LiveDisabled):
        start(profile.pk, "x")


def test_an_unknown_profile_is_a_typed_error() -> None:
    with pytest.raises(ProviderUnavailable):
        start(987654, "facebook")


def test_a_write_cancelled_by_a_tool_timeout_leaves_no_state(
    env, profile, monkeypatch
) -> None:
    """The tool timed out while the state row was being written: the row must not survive."""
    env(META_ENV)
    token = cancel.CancelToken()
    real = accounts.start_connect

    def start_then_time_out(*args, **kwargs):
        url = real(*args, **kwargs)
        token.cancel_nowait()  # the loop gave up while the worker thread was still writing
        return url

    monkeypatch.setattr(accounts, "start_connect", start_then_time_out)
    reset = cancel.current.set(token)
    try:
        with pytest.raises(cancel.WriteCancelled):
            start(profile.pk, "facebook")
    finally:
        cancel.current.reset(reset)
    assert OAuthState.objects.count() == 0


def test_a_fast_call_under_a_token_still_commits(env, profile) -> None:
    env(META_ENV)
    token = cancel.CancelToken()
    reset = cancel.current.set(token)
    try:
        link = start(profile.pk, "facebook")
    finally:
        cancel.current.reset(reset)
    assert link.url and OAuthState.objects.count() == 1 and token.commits == 1
