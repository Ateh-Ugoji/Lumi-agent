"""IsProfileOwner and the error handler, exercised through throwaway views."""

import pytest
from django.db import IntegrityError
from django.urls import path
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.accounts.models import AuthToken, User
from apps.core.errors import ApiError
from apps.core.permissions import IsProfileOwner
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db


class ProfileView(APIView):
    permission_classes = [IsProfileOwner]

    def get(self, request, profile_id=None):
        return Response({"profile": request.profile.pk})

    def post(self, request, profile_id=None):
        return Response(
            {"profile": getattr(request, "profile", None) and request.profile.pk}
        )


class RaisesView(APIView):
    def get(self, request, kind):
        raise {
            "api": ApiError(
                "conflict", "Choca.", status_code=409, details={"field": ["x"]}
            ),
            "forbidden": exceptions.PermissionDenied(),
            "boom": RuntimeError("secret internals"),
            "integrity": IntegrityError(
                "duplicate key value violates unique constraint"
            ),
        }[kind]


urlpatterns = [
    path("t/profiles/<int:profile_id>", ProfileView.as_view()),
    path("t/profiles-any/<profile_id>", ProfileView.as_view()),
    path("t/chat", ProfileView.as_view()),
    path("t/raise/<kind>", RaisesView.as_view()),
]


@pytest.fixture(autouse=True)
def _urls(settings):
    settings.ROOT_URLCONF = __name__


def make_profile(email, handle):
    user = User.objects.create_user(email)
    h = SocialHandle.objects.create(platform="x", handle_normalized=handle)
    return user, SocialProfile.objects.create(user=user, handle=h)


def client_for(user):
    _, key = AuthToken.issue(user)
    client = APIClient(raise_request_exception=False)
    client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    return client


def test_owner_passes_on_url_kwarg():
    user, profile = make_profile("a@example.com", "aaa")
    response = client_for(user).get(f"/t/profiles/{profile.pk}")
    assert response.status_code == 200 and response.json() == {"profile": profile.pk}


def test_other_users_profile_is_not_found_not_forbidden():
    _, mine = make_profile("a@example.com", "aaa")
    other, _ = make_profile("b@example.com", "bbb")
    response = client_for(other).get(f"/t/profiles/{mine.pk}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_missing_profile_looks_the_same_as_someone_elses():
    _, mine = make_profile("a@example.com", "aaa")
    other, _ = make_profile("b@example.com", "bbb")
    theirs = client_for(other).get(f"/t/profiles/{mine.pk}").json()
    missing = client_for(other).get("/t/profiles/999999").json()
    assert theirs == missing


def test_profile_id_from_query_string_and_body():
    user, profile = make_profile("a@example.com", "aaa")
    other, _ = make_profile("b@example.com", "bbb")
    assert client_for(user).get(f"/t/chat?profile_id={profile.pk}").status_code == 200
    assert client_for(other).get(f"/t/chat?profile_id={profile.pk}").status_code == 404
    assert (
        client_for(other)
        .post("/t/chat", {"profile_id": profile.pk}, format="json")
        .status_code
        == 404
    )


def test_malformed_profile_id_is_not_found():
    user, _ = make_profile("a@example.com", "aaa")
    assert client_for(user).get("/t/profiles-any/abc").status_code == 404
    assert client_for(user).get("/t/chat?profile_id=1;drop").status_code == 404


def test_route_without_profile_id_is_not_restricted():
    user, _ = make_profile("a@example.com", "aaa")
    assert client_for(user).post("/t/chat", {}, format="json").status_code == 200


def test_anonymous_gets_401_before_ownership_is_checked():
    _, profile = make_profile("a@example.com", "aaa")
    response = APIClient().get(f"/t/profiles/{profile.pk}")
    assert response.status_code == 401


def test_api_error_carries_code_status_and_details():
    user, _ = make_profile("a@example.com", "aaa")
    response = client_for(user).get("/t/raise/api")
    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "Choca.", "details": {"field": ["x"]}}
    }


def test_forbidden_format():
    user, _ = make_profile("a@example.com", "aaa")
    response = client_for(user).get("/t/raise/forbidden")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("kind", ["boom", "integrity"])
def test_unexpected_errors_never_leak_internals(kind):
    user, _ = make_profile("a@example.com", "aaa")
    response = client_for(user).get(f"/t/raise/{kind}")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Error interno."}
    }
    assert "secret" not in response.content.decode()
    assert "duplicate" not in response.content.decode()
