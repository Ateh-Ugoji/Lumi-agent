"""``services.update_handle_avatar``: the refresh that ``get_or_create_handle`` does not do."""

import pytest
from asgiref.sync import async_to_sync
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.profiles import services
from apps.profiles.models import SocialHandle

pytestmark = pytest.mark.django_db
OLD = "https://cdn.example/old.jpg"
NEW = "https://cdn.example/new.jpg"


def make(avatar_url=""):
    return services.get_or_create_handle("x", "rival", avatar_url=avatar_url)


def stored(handle_id):
    return SocialHandle.objects.get(pk=handle_id)


def test_a_new_valid_url_replaces_the_old_one_and_says_so():
    hid = make(OLD)
    assert services.update_handle_avatar(hid, NEW) is True
    assert stored(hid).avatar_url == NEW


def test_it_fills_a_handle_that_has_no_photo():
    hid = make()
    assert services.update_handle_avatar(hid, OLD) is True
    assert stored(hid).avatar_url == OLD


def test_the_same_url_changes_nothing_and_does_not_touch_updated_at():
    hid = make(OLD)
    before = stored(hid).updated_at
    assert services.update_handle_avatar(hid, OLD) is False
    assert stored(hid).updated_at == before


def test_a_change_moves_updated_at():
    hid = make(OLD)
    before = stored(hid).updated_at
    services.update_handle_avatar(hid, NEW)
    assert stored(hid).updated_at > before


@pytest.mark.parametrize("blank", [None, "", "   ", "\n"])
def test_a_blank_value_never_erases_the_photo(blank):
    hid = make(OLD)
    assert services.update_handle_avatar(hid, blank) is False
    assert stored(hid).avatar_url == OLD


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "ftp://cdn.example/a.jpg",
        "//cdn.example/a.jpg",
        "/avatars/a.jpg",
        "cdn.example/a.jpg",
        "https://",
        "https:///a.jpg",
        "https://cdn.example/a b.jpg",
        "https://cdn.example/a.jpg\n<script>",
        "https://[::1/a.jpg",
        "https://cdn.example/" + "a" * 2100,
    ],
)
def test_an_invalid_url_is_ignored(bad):
    hid = make(OLD)
    assert services.update_handle_avatar(hid, bad) is False
    assert stored(hid).avatar_url == OLD


def test_http_and_uppercase_schemes_are_accepted_and_the_url_is_stripped():
    hid = make()
    assert services.update_handle_avatar(hid, "  HTTP://cdn.example/a.jpg  ") is True
    assert stored(hid).avatar_url == "HTTP://cdn.example/a.jpg"


def test_an_unknown_handle_is_not_an_error():
    assert services.update_handle_avatar(999_999, NEW) is False


def test_only_the_named_handle_changes():
    one = make(OLD)
    two = services.get_or_create_handle("x", "other", avatar_url=OLD)
    services.update_handle_avatar(one, NEW)
    assert stored(two).avatar_url == OLD


def test_fill_only_get_or_create_still_keeps_what_the_refresh_wrote():
    hid = make(OLD)
    services.update_handle_avatar(hid, NEW)
    services.get_or_create_handle("x", "rival", avatar_url="https://cdn.example/x.jpg")
    assert stored(hid).avatar_url == NEW


def test_it_is_one_conditional_update_and_nothing_else():
    hid = make(OLD)
    with CaptureQueriesContext(connection) as ctx:
        services.update_handle_avatar(hid, NEW)
    assert len(ctx) == 1
    sql = ctx[0]["sql"]
    assert sql.startswith('UPDATE "social_handles"')
    assert "NOT" in sql and '"avatar_url" =' in sql


def test_an_invalid_url_does_not_even_query():
    hid = make(OLD)
    with CaptureQueriesContext(connection) as ctx:
        services.update_handle_avatar(hid, "javascript:alert(1)")
    assert len(ctx) == 0


def test_the_async_twin_does_the_same():
    hid = make(OLD)
    assert async_to_sync(services.aupdate_handle_avatar)(hid, NEW) is True
    assert stored(hid).avatar_url == NEW


# --- the connected account's own photo -------------------------------------------------------


@pytest.fixture
def profile(django_user_model):
    user = django_user_model.objects.create_user("owner@example.com")
    profile_id, _ = services.get_or_create_profile(user.pk, "x", "Me")
    return profile_id


def profile_photo(profile_id):
    return SocialHandle.objects.get(social_profiles__pk=profile_id).avatar_url


def test_the_accounts_photo_goes_to_the_handle_of_its_profile(profile):
    assert services.update_profile_avatar(profile, OLD, username="me") is True
    assert profile_photo(profile) == OLD
    assert services.update_profile_avatar(profile, NEW, username="@Me") is True
    assert profile_photo(profile) == NEW
    assert services.update_profile_avatar(profile, NEW, username="me") is False


def test_another_account_cannot_repaint_the_handle(profile):
    assert (
        services.update_profile_avatar(profile, NEW, username="someone_else") is False
    )
    assert profile_photo(profile) == ""


@pytest.mark.parametrize("username", [None, "", "not a handle!"])
def test_a_username_that_cannot_be_checked_writes_nothing(profile, username):
    assert services.update_profile_avatar(profile, NEW, username=username) is False
    assert profile_photo(profile) == ""


def test_a_profile_that_does_not_exist_is_not_an_error():
    assert services.update_profile_avatar(999_999, NEW, username="me") is False


def test_a_blank_photo_keeps_the_one_the_profile_has(profile):
    services.update_profile_avatar(profile, OLD, username="me")
    assert services.update_profile_avatar(profile, None, username="me") is False
    assert profile_photo(profile) == OLD


def test_the_profile_twin_is_async_too(profile):
    ok = async_to_sync(services.aupdate_profile_avatar)(profile, NEW, username="me")
    assert ok is True
