"""The admin is staff-only, read-only, and can never show an encrypted column or a secret hash."""

import pytest
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.admin import AdminSite
from django.core import checks
from django.db import connection, models
from django.test import Client
from django.test.utils import isolate_apps
from django.urls import path, reverse

from apps.accounts.models import AuthToken, User
from apps.core.admin import SafeModelAdmin, check_admin_hides_encrypted_fields
from apps.core.fields import EncryptedTextField
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db

PLAINTEXT = "PLAINTEXT-oauth-token-4f9a1c"


@pytest.fixture
def staff():
    return User.objects.create_superuser("root@example.com", "correct-horse-battery")


@pytest.fixture
def staff_client(staff):
    client = Client()
    client.force_login(staff)
    return client


# ----- access control -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["/admin/", "/admin/profiles/post/", "/admin/accounts/user/"]
)
def test_anonymous_is_sent_to_the_login_page(url):
    response = Client().get(url)
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


def test_a_regular_user_cannot_enter():
    user = User.objects.create_user("ana@example.com", "correct-horse-battery")
    client = Client()
    client.force_login(user)
    for url in ("/admin/", "/admin/accounts/user/", "/admin/accounts/user/1/change/"):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"].startswith(
            "/admin/login/"
        )


def test_staff_without_superuser_still_needs_permissions():
    user = User.objects.create_user(
        "ops@example.com", "correct-horse-battery", is_staff=True
    )
    client = Client()
    client.force_login(user)
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/accounts/user/").status_code == 403


def test_the_api_token_does_not_open_the_admin():
    user = User.objects.create_superuser("root@example.com", "correct-horse-battery")
    _, key = AuthToken.issue(user)
    response = Client().get("/admin/", HTTP_AUTHORIZATION=f"Token {key}")
    assert response.status_code == 302


def test_the_admin_is_read_only(staff_client, staff):
    assert staff_client.get("/admin/accounts/user/add/").status_code == 403
    assert (
        staff_client.post(f"/admin/accounts/user/{staff.pk}/delete/").status_code == 403
    )
    assert (
        staff_client.post(
            f"/admin/accounts/user/{staff.pk}/change/", {"email": "x@example.com"}
        ).status_code
        == 403
    )
    staff.refresh_from_db()
    assert staff.email == "root@example.com"


# ----- every registered model renders ---------------------------------------------------------


def test_every_registered_changelist_renders(staff_client):
    registered = [
        m
        for m in admin.site._registry
        if m._meta.app_label in {"core", "accounts", "profiles", "chat"}
    ]
    assert len(registered) >= 16
    for model in registered:
        url = reverse(
            f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
        )
        assert staff_client.get(url).status_code == 200, model


def test_no_registered_admin_is_outside_the_safe_base():
    for model_admin in admin.site._registry.values():
        assert isinstance(model_admin, SafeModelAdmin), type(model_admin)


def test_system_check_passes_for_the_real_registry():
    assert check_admin_hides_encrypted_fields(None) == []


# ----- secrets that must not show -------------------------------------------------------------


def test_password_hash_and_token_hash_never_render(staff_client, staff):
    _, key = AuthToken.issue(staff, name="laptop")
    token = AuthToken.objects.get()
    pages = [
        staff_client.get("/admin/accounts/user/"),
        staff_client.get(f"/admin/accounts/user/{staff.pk}/change/"),
        staff_client.get("/admin/accounts/authtoken/"),
        staff_client.get(f"/admin/accounts/authtoken/{token.pk}/change/"),
        staff_client.get("/admin/accounts/user/?q=root"),
    ]
    for page in pages:
        assert page.status_code == 200
        body = page.content.decode()
        assert staff.password not in body
        assert token.key_hash not in body
        assert key not in body
        assert "pbkdf2" not in body and "md5$" not in body


def test_imported_rows_render_in_change_pages(staff_client):
    user = User.objects.create_user("ana@example.com")
    handle = SocialHandle.objects.create(platform="x", handle_normalized="ana")
    profile = SocialProfile.objects.create(user=user, handle=handle)
    for url in (
        f"/admin/profiles/socialhandle/{handle.pk}/change/",
        f"/admin/profiles/socialprofile/{profile.pk}/change/",
    ):
        assert staff_client.get(url).status_code == 200


# ----- encrypted fields -----------------------------------------------------------------------


@pytest.fixture
def secret_admin(settings):
    """A throwaway model with an EncryptedTextField, shown by a deliberately careless admin."""
    settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with isolate_apps("apps.core"):

        class Secret(models.Model):
            name = models.CharField(max_length=40)
            token = EncryptedTextField()

            class Meta:
                app_label = "core"

        class CarelessAdmin(SafeModelAdmin):
            # Everything an author could do to put the column on a page.
            fields = ("name", "token")
            readonly_fields = ("token",)
            list_display = ("name", "token")
            list_filter = ("token",)
            search_fields = ("name", "token", "^token", "token__icontains")

        site = AdminSite(name="careless")
        site.register(Secret, CarelessAdmin)
        module = type("Urls", (), {"urlpatterns": [path("careless/", site.urls)]})
        settings.ROOT_URLCONF = module
        with connection.schema_editor() as editor:
            editor.create_model(Secret)
        row = Secret.objects.create(name="meta", token=PLAINTEXT)
        yield Secret, row
        with connection.schema_editor() as editor:
            editor.delete_model(Secret)


def test_encrypted_plaintext_never_appears_in_list_or_change_pages(
    secret_admin, staff_client
):
    _, row = secret_admin
    with connection.cursor() as cursor:
        cursor.execute("SELECT token FROM core_secret")
        ciphertext = cursor.fetchone()[0]
    assert ciphertext != PLAINTEXT  # the column really is encrypted at rest

    urls = [
        "/careless/core/secret/",
        "/careless/core/secret/?q=PLAINTEXT",
        "/careless/core/secret/?token=" + PLAINTEXT,
        f"/careless/core/secret/{row.pk}/change/",
    ]
    for url in urls:
        response = staff_client.get(url, follow=True)
        body = response.content.decode()
        assert PLAINTEXT not in body, url
        assert ciphertext not in body, url
    # the non-secret column still shows, so the pages are not simply empty
    assert "meta" in staff_client.get("/careless/core/secret/").content.decode()


def test_system_check_rejects_an_unsafe_admin_for_a_model_with_encrypted_fields(
    settings,
):
    settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with isolate_apps("apps.core"):

        class Vault(models.Model):
            token = EncryptedTextField()

            class Meta:
                app_label = "core"

        admin.site.register(Vault, admin.ModelAdmin)
        try:
            errors = check_admin_hides_encrypted_fields(None)
        finally:
            admin.site.unregister(Vault)
    assert [e.id for e in errors] == ["lumi.E001"]
    assert isinstance(errors[0], checks.Error) and "token" in errors[0].msg
