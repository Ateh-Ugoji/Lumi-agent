# ruff: noqa: F811
"""The OAuth state belongs to the user who started it (proof P1 of the security review).

The provider redirect lands on a PUBLIC endpoint with no credentials. If that endpoint finished
the grant, a victim who opened an attacker's authorize link would attach their own provider
account to the attacker. So the callback exchanges nothing and the logged-in frontend finishes
the grant with ``POST /connections/<provider>/complete``, checked against the state's owner.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from rest_framework.test import APIClient

from apps.connections.models import ConnectedAccount, OAuthState
from apps.connections.tests.db.test_api import (  # noqa: F401  fixtures and helpers
    api,
    complete,
    env,
    providers,
    start_meta,
    wiring,
)

pytestmark = pytest.mark.django_db


def handoff(state: str, code: str = "c0de"):
    return APIClient().get(
        "/api/v1/connections/meta/callback", {"code": code, "state": state}
    )


def test_the_public_callback_exchanges_nothing(api, env, providers, user) -> None:
    state = start_meta(api, env, providers)
    response = handoff(state)
    assert response.status_code == 302
    parts = urlsplit(response["Location"])
    assert (
        parts.query == ""
    )  # no code in the query string, so no log or Referer sees it
    assert parse_qs(parts.fragment) == {
        "connect": ["meta"],
        "code": ["c0de"],
        "state": [state],
    }
    assert providers.requests("meta") == []  # the provider was never called
    assert ConnectedAccount.objects.count() == 0
    assert (
        OAuthState.objects.get(state=state).consumed_at is None
    )  # still usable by its owner


def test_a_victim_who_opens_the_attackers_link_connects_nothing(
    api, other_user, env, providers, user
) -> None:
    attacker_state = start_meta(api, env, providers)  # the attacker's authorize_url
    handoff(attacker_state)  # the victim's browser comes back with the attacker's grant
    refused = complete("meta", attacker_state, "c0de", user=other_user)
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "connections.state_invalid"
    assert ConnectedAccount.objects.count() == 0  # neither the attacker nor the victim
    assert (
        providers.requests("meta") == []
    )  # and no code was exchanged for the victim's grant


def test_the_owner_finishes_with_their_own_token(api, env, providers, user) -> None:
    state = start_meta(api, env, providers)
    response = complete("meta", state, "c0de", user=user)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True and body["accounts"] == 2
    assert ConnectedAccount.objects.filter(user=user).count() == 2


def test_complete_needs_a_login_and_a_known_provider(api, env, providers) -> None:
    state = start_meta(api, env, providers)
    anonymous = APIClient().post(
        "/api/v1/connections/meta/complete",
        {"code": "c", "state": state},
        format="json",
    )
    assert anonymous.status_code == 401
    assert OAuthState.objects.get(state=state).consumed_at is None
    assert api.post(
        "/api/v1/connections/myspace/complete", {}, format="json"
    ).status_code in (
        400,
        404,
    )
    pfm = api.post(
        "/api/v1/connections/pfm/complete", {"code": "c", "state": "s"}, format="json"
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
