# ruff: noqa: F811
"""``POST /connections/{provider}/link`` (CONTRATOS 4.1) over Postgres, no network."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.connections.models import AccountStatus, ConnectedAccount
from apps.connections.tests.db.test_api import (  # noqa: F401  fixtures and helpers
    api,
    client_for,
    env,
    providers,
    wiring,
)
from apps.connections.tests.db.test_publish_api import body, post
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db

LINK = "/api/v1/connections/meta/link"


def make_profile(user, platform="facebook", name="page-1") -> SocialProfile:
    handle = SocialHandle.objects.create(platform=platform, handle_normalized=name)
    return SocialProfile.objects.create(user=user, handle=handle)


def make_account(user, ext, *, provider="meta", platform="facebook", **extra):
    return ConnectedAccount.objects.create(
        user=user,
        provider=provider,
        external_account_id=ext,
        platform=platform,
        access_token=f"token-{ext}",
        display_name=f"Page {ext}",
        **extra,
    )


def link(api, account, profile, provider="meta"):
    return api.post(
        f"/api/v1/connections/{provider}/link",
        {"account_id": account, "profile_id": profile.pk},
        format="json",
    )


def linked_to(ext, provider="meta"):
    row = ConnectedAccount.objects.get(provider=provider, external_account_id=ext)
    return row.social_profile_id


def test_it_needs_a_token(client) -> None:
    reply = client.post(LINK, {}, content_type="application/json")
    assert reply.status_code == 401


def test_a_page_is_linked_to_the_profile(api, user) -> None:
    profile = make_profile(user)
    make_account(user, "1001")
    reply = link(api, "1001", profile)
    assert reply.status_code == 200
    data = reply.json()
    assert data["provider"] == "meta" and data["profile_id"] == profile.pk
    assert (
        data["account"]["id"] == "1001" and data["account"]["profile_id"] == profile.pk
    )
    assert data["replaced_account_id"] is None and data["moved_from_profile_id"] is None
    assert linked_to("1001") == profile.pk


def test_the_answer_never_carries_a_token(api, user) -> None:
    profile = make_profile(user)
    make_account(user, "1001")
    text = link(api, "1001", profile).content.decode()
    assert "token-1001" not in text and "access_token" not in text


def test_repeating_the_request_writes_nothing_and_answers_the_same(api, user) -> None:
    profile = make_profile(user)
    make_account(user, "1001")
    link(api, "1001", profile)
    with CaptureQueriesContext(connection) as ctx:
        again = link(api, "1001", profile)
    assert again.status_code == 200
    assert again.json()["replaced_account_id"] is None
    assert again.json()["moved_from_profile_id"] is None
    writes = [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        and "auth_tokens" not in q["sql"]
    ]
    assert writes == []


def test_a_second_page_replaces_the_first_which_stays_connected(api, user) -> None:
    profile = make_profile(user)
    make_account(user, "1001")
    make_account(user, "1002")
    link(api, "1001", profile)
    reply = link(api, "1002", profile)
    assert reply.status_code == 200
    assert reply.json()["replaced_account_id"] == "1001"
    assert linked_to("1002") == profile.pk and linked_to("1001") is None
    assert ConnectedAccount.objects.get(external_account_id="1001").status == (
        AccountStatus.ACTIVE
    )


def test_an_account_moves_between_profiles(api, user) -> None:
    first = make_profile(user, name="page-1")
    second = make_profile(user, name="page-2")
    make_account(user, "1001")
    link(api, "1001", first)
    reply = link(api, "1001", second)
    assert reply.status_code == 200
    assert reply.json()["moved_from_profile_id"] == first.pk
    assert linked_to("1001") == second.pk
    assert not ConnectedAccount.objects.filter(social_profile=first).exists()


def test_a_move_onto_a_profile_that_has_another_account_does_both(api, user) -> None:
    first = make_profile(user, name="page-1")
    second = make_profile(user, name="page-2")
    make_account(user, "1001")
    make_account(user, "1002")
    link(api, "1001", first)
    link(api, "1002", second)
    reply = link(api, "1001", second)
    assert reply.status_code == 200
    data = reply.json()
    assert data["replaced_account_id"] == "1002"
    assert data["moved_from_profile_id"] == first.pk
    assert linked_to("1001") == second.pk and linked_to("1002") is None


def test_someone_elses_account_is_a_404(api, other_user, user) -> None:
    profile = make_profile(user)
    make_account(other_user, "9001")
    reply = link(api, "9001", profile)
    assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found"
    assert linked_to("9001") is None


def test_an_account_that_does_not_exist_is_the_same_404(api, user) -> None:
    profile = make_profile(user)
    reply = link(api, "nope", profile)
    assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found"


def test_someone_elses_profile_is_a_404(api, other_user, user) -> None:
    theirs = make_profile(other_user)
    make_account(user, "1001")
    reply = link(api, "1001", theirs)
    assert reply.status_code == 404
    assert linked_to("1001") is None


def test_an_account_of_another_provider_is_not_found_under_this_one(api, user) -> None:
    profile = make_profile(user, "linkedin", "me")
    make_account(user, "li-1", provider="linkedin", platform="linkedin")
    assert link(api, "li-1", profile, provider="meta").status_code == 404


def test_google_has_no_links(api, user) -> None:
    profile = make_profile(user)
    reply = link(api, "x", profile, provider="google")
    assert reply.status_code == 400
    assert reply.json()["error"]["code"] == "connections.unsupported"


def test_an_unknown_provider_is_a_404(api, user) -> None:
    profile = make_profile(user)
    assert link(api, "x", profile, provider="myspace").status_code == 404


@pytest.mark.parametrize("state", [AccountStatus.REVOKED, AccountStatus.ERROR])
def test_a_dead_account_must_be_reconnected_first(api, user, state) -> None:
    profile = make_profile(user)
    make_account(user, "1001", status=state)
    reply = link(api, "1001", profile)
    assert reply.status_code == 409
    assert reply.json()["error"]["code"] == "connections.account_unusable"
    assert linked_to("1001") is None


@pytest.mark.parametrize("state", [AccountStatus.ACTIVE, AccountStatus.LIMITED])
def test_a_live_account_links(api, user, state) -> None:
    profile = make_profile(user)
    make_account(user, "1001", status=state)
    assert link(api, "1001", profile).status_code == 200


def test_a_page_does_not_link_to_an_instagram_profile(api, user) -> None:
    """A Meta Page is stored as ``facebook``: the adapter has no Instagram surface."""
    profile = make_profile(user, "instagram", "ig-me")
    make_account(user, "1001", platform="facebook")
    reply = link(api, "1001", profile)
    assert reply.status_code == 409
    error = reply.json()["error"]
    assert error["code"] == "connections.platform_mismatch"
    assert error["details"] == {
        "account_platform": "facebook",
        "profile_platform": "instagram",
    }
    assert linked_to("1001") is None


def test_an_account_without_platform_links_to_any_profile(api, user) -> None:
    profile = make_profile(user, "instagram", "ig-me")
    make_account(user, "1001", platform="")
    assert link(api, "1001", profile).status_code == 200


def test_a_post_for_me_account_links_to_the_matching_network_only(api, user) -> None:
    ig = make_profile(user, "instagram", "ig-me")
    tt = make_profile(user, "tiktok", "tt-me")
    make_account(user, "sa_1", provider="pfm", platform="instagram")
    assert link(api, "sa_1", tt, provider="pfm").status_code == 409
    assert link(api, "sa_1", ig, provider="pfm").status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"account_id": "1001"},
        {"profile_id": 1},
        {"account_id": "", "profile_id": 1},
        {"account_id": "1001", "profile_id": "abc"},
        {"account_id": "1001", "profile_id": 0},
    ],
)
def test_a_bad_body_is_a_validation_error(api, user, payload) -> None:
    make_profile(user)
    reply = api.post(LINK, payload, format="json")
    assert reply.status_code == 400
    assert reply.json()["error"]["code"] == "validation_error"


def test_publishing_stops_saying_not_connected_after_the_link(
    api, user, env, providers
) -> None:
    from apps.connections.tests.db.test_api import META_ENV

    env(META_ENV)
    profile = make_profile(user)
    make_account(user, "1001")
    payload = body(profile, dry_run=True)
    before = post(api, payload)
    assert before.status_code == 409
    assert before.json()["error"]["code"] == "publish.not_connected"
    assert link(api, "1001", profile).status_code == 200
    after = post(api, payload)
    assert after.json().get("error", {}).get("code") != "publish.not_connected"
    assert after.status_code == 200


def test_a_race_between_two_links_for_one_profile_ends_with_one_account(
    api, user
) -> None:
    profile = make_profile(user)
    make_account(user, "1001")
    make_account(user, "1002")
    link(api, "1001", profile)
    link(api, "1002", profile)
    link(api, "1001", profile)
    assert ConnectedAccount.objects.filter(social_profile=profile).count() == 1


def test_the_profile_and_the_accounts_are_locked_for_the_whole_link(api, user) -> None:
    profile = make_profile(user)
    make_account(user, "1001")
    with CaptureQueriesContext(connection) as ctx:
        link(api, "1001", profile)
    locking = [q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"]]
    assert any("social_profiles" in sql for sql in locking)
    assert any("connected_accounts" in sql for sql in locking)


def test_the_provider_is_checked_before_the_body(api, user) -> None:
    assert (
        api.post("/api/v1/connections/google/link", {}, format="json").status_code
        == 400
    )
    reply = api.post("/api/v1/connections/google/link", {}, format="json")
    assert reply.json()["error"]["code"] == "connections.unsupported"
    assert (
        api.post("/api/v1/connections/myspace/link", {}, format="json").status_code
        == 404
    )
