"""The URL tree matches CONTRATOS: every public path resolves once and none shadows another."""

import pytest
from django.urls import Resolver404, resolve, reverse

pytestmark = pytest.mark.django_db

CONNECTION_PATHS = [
    ("/api/v1/connections/x/connect", "connections-connect"),
    ("/api/v1/connections/x/callback", "connections-callback"),
    ("/api/v1/connections/x/status", "connections-status"),
    ("/api/v1/connections/x", "connections-provider"),
]


@pytest.mark.parametrize(("path", "name"), CONNECTION_PATHS)
def test_connections_routes_are_mounted_under_api_v1(path, name):
    assert resolve(path).url_name == name
    assert reverse(name, kwargs={"provider": "x"}) == path


def test_auth_routes_still_resolve_and_no_route_is_declared_twice():
    assert resolve("/api/v1/auth/login").url_name == "auth-login"
    with pytest.raises(Resolver404):
        resolve("/api/v1/connections")
    patterns = []

    def walk(urlpatterns, prefix=""):
        for entry in urlpatterns:
            if hasattr(entry, "url_patterns"):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            else:
                patterns.append(prefix + str(entry.pattern))

    from config.urls import urlpatterns

    walk(urlpatterns)
    shapes = [p.replace("<str:provider>", "<p>") for p in patterns]
    # ProviderView is intentionally served at two paths: bare and /status
    assert len(set(shapes)) == len(shapes)


def test_connect_requires_a_token(client):
    response = client.post("/api/v1/connections/x/connect")
    assert response.status_code == 401
    assert response.json()["error"]["code"]
