# ruff: noqa: F811
"""The OAuth state belongs to the user who started it (proof P1 of the security review).

The provider redirects to a FRONTEND page. That page posts ``{code, state}`` to
``POST /connections/<provider>/callback`` with the user's Token. If the API finished the grant for
whoever opened the redirect, a victim who opened an attacker's authorize link would attach their
own provider account to the attacker. The state is consumed only for its owner, in one UPDATE.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.connections.models import ConnectedAccount, OAuthState
from apps.connections.tests.db.test_api import (  # noqa: F401  fixtures and helpers
    api,
    complete,
    complete_body,
    env,
    providers,
    start_meta,
    wiring,
)

pytestmark = pytest.mark.django_db


def test_a_victim_who_opens_the_attackers_link_connects_nothing(
    api, other_user, env, providers, user
) -> None:
    """The attack: B posts the state A started. Nothing links and A's state still works."""
    attacker_state = start_meta(api, env, providers)  # the attacker's authorize_url
    refused = complete("meta", attacker_state, "c0de", user=other_user)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "connections.state_mismatch"
    assert ConnectedAccount.objects.count() == 0  # neither the attacker nor the victim
    assert (
        providers.requests("meta") == []
    )  # no code was exchanged for the victim's grant
    assert OAuthState.objects.get(state=attacker_state).consumed_at is None
    ok = complete("meta", attacker_state, "c0de", user=user)  # the owner still finishes
    assert ok.status_code == 200
    assert not ConnectedAccount.objects.filter(user=other_user).exists()
    assert ConnectedAccount.objects.filter(user=user).count() == 2


def test_a_mismatch_does_not_tell_apart_unknown_states_from_expired_ones(
    api, other_user, env, providers, user
) -> None:
    state = start_meta(api, env, providers)
    OAuthState.objects.filter(state=state).update(expires_at="2000-01-01T00:00:00Z")
    expired = complete("meta", state, "c0de", user=other_user)
    unknown = complete("meta", "nope", "c0de", user=other_user)
    assert expired.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert expired.status_code == unknown.status_code == 400


def test_the_user_saying_no_burns_the_state(api, env, providers, user) -> None:
    state = start_meta(api, env, providers)
    denied = complete_body(
        "meta", {"state": state, "error": "access_denied"}, user=user
    )
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "connections.access_denied"
    assert OAuthState.objects.get(state=state).consumed_at is not None
    assert complete("meta", state, "c0de", user=user).status_code == 400


def test_someone_elses_denial_does_not_burn_my_state(
    api, other_user, env, providers, user
) -> None:
    state = start_meta(api, env, providers)
    refused = complete_body("meta", {"state": state, "error": "x"}, user=other_user)
    assert refused.status_code == 409
    assert OAuthState.objects.get(state=state).consumed_at is None


def test_the_redirect_uri_is_a_frontend_page(api, env, providers) -> None:
    state = start_meta(api, env, providers)
    assert state
    url = OAuthState.objects.get(state=state)
    assert url.provider == "meta"
    from apps.connections.accounts import get_config

    assert get_config().redirect_uri("meta").startswith(get_config().frontend_url)
    assert get_config().redirect_uri("meta").endswith("/connections/meta/callback")


def test_the_owner_finishes_with_their_own_token(api, env, providers, user) -> None:
    state = start_meta(api, env, providers)
    response = complete("meta", state, "c0de", user=user)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True and body["accounts"] == 2
    assert ConnectedAccount.objects.filter(user=user).count() == 2


def test_callback_needs_a_login_and_a_known_provider(api, env, providers) -> None:
    state = start_meta(api, env, providers)
    anonymous = APIClient().post(
        "/api/v1/connections/meta/callback",
        {"code": "c", "state": state},
        format="json",
    )
    assert anonymous.status_code == 401
    assert OAuthState.objects.get(state=state).consumed_at is None
    assert api.post(
        "/api/v1/connections/myspace/callback", {}, format="json"
    ).status_code in (
        400,
        404,
    )
    pfm = api.post(
        "/api/v1/connections/pfm/callback", {"code": "c", "state": "s"}, format="json"
    )
    assert pfm.status_code == 400


def test_a_state_completes_only_once(api, env, providers, user) -> None:
    state = start_meta(api, env, providers)
    assert complete("meta", state, "c0de", user=user).status_code == 200
    again = complete("meta", state, "c0de", user=user)
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "connections.state_invalid"


def test_a_state_for_another_provider_is_refused(api, env, providers, user) -> None:
    state = start_meta(api, env, providers)
    wrong = complete("linkedin", state, "c0de", user=user)
    assert wrong.status_code == 400
