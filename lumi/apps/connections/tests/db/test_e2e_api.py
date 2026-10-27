"""The whole API journey over the real ROOT_URLCONF, with the simulated providers of ``e2e.sim``.

The same flow the browser walks in ``e2e/tests/journey.spec.ts``, without a browser: register,
add a profile, connect Meta through the real callback, chat, publish (dry run, then for real),
disconnect. No key and no network.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from rest_framework.test import APIClient

from apps.core import agent_runtime
from e2e import sim

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def world(monkeypatch):
    for name in ("META_APP_ID", "META_APP_SECRET", "PFM_JWT_TOKEN", "X_LIVE_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("META_APP_ID", "e2e-meta-app")
    monkeypatch.setenv("META_APP_SECRET", "e2e-meta-secret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3010")
    undo = sim.install()
    agent_runtime.set_runtime(sim.FakeRuntime())
    sim.WORLD.meta_pages = 1
    yield
    agent_runtime.set_runtime(None)
    undo()


def test_register_connect_chat_publish_and_disconnect() -> None:
    anon = APIClient()
    signup = anon.post(
        "/api/v1/auth/register",
        {"email": "journey@example.com", "password": "correct-horse-123"},
        format="json",
    )
    assert signup.status_code == 201
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Token {signup.json()['token']}")

    profile = api.post(
        "/api/v1/profiles", {"platform": "facebook", "handle": "demo"}, format="json"
    )
    assert profile.status_code == 201
    profile_id = profile.json()["id"]

    # Connect: the API hands out the provider URL. The provider redirects to a FRONTEND page,
    # which posts the code and state with the user's Token.
    connect = api.post(
        "/api/v1/connections/meta/connect", {"profile_id": profile_id}, format="json"
    )
    assert connect.status_code == 200
    query = parse_qs(urlsplit(connect.json()["authorize_url"]).query)
    assert query["redirect_uri"][0].startswith("http://localhost:3010/")
    state = query["state"][0]
    done = api.post(
        "/api/v1/connections/meta/callback",
        {"code": "c0de", "state": state},
        format="json",
    )
    assert done.status_code == 200 and done.json()["connected"] is True

    status = api.get("/api/v1/connections/meta/status").json()
    assert status["connected"] is True
    assert "FAKE" not in str(status), "no token reaches the client"

    # Chat: the scripted agent answers through the real chat route.
    chat = api.post(
        "/api/v1/chat", {"profile_id": profile_id, "message": "hola"}, format="json"
    )
    assert chat.status_code == 200

    # Publish: the dry run sends nothing, the real publish needs confirm and a key.
    body = {
        "profile_id": profile_id,
        "platform": "facebook",
        "text": "Lanzamos la versión nueva hoy",
    }
    dry = api.post("/api/v1/publish", {**body, "dry_run": True}, format="json")
    assert dry.status_code == 200 and dry.json()["dry_run"] is True
    unconfirmed = api.post(
        "/api/v1/publish",
        {**body, "confirm": False},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k1",
    )
    assert unconfirmed.status_code == 400
    real = api.post(
        "/api/v1/publish",
        {**body, "confirm": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k1",
    )
    assert real.status_code == 201
    replay = api.post(
        "/api/v1/publish",
        {**body, "confirm": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k1",
    )
    assert replay.status_code in (200, 201)

    # Disconnect, then publishing says what to do instead of failing in the dark.
    gone = api.delete("/api/v1/connections/meta")
    assert gone.status_code in (200, 204)
    assert api.get("/api/v1/connections/meta/status").json()["connected"] is False
    after = api.post(
        "/api/v1/publish",
        {**body, "confirm": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k2",
    )
    assert after.status_code == 409
    assert after.json()["error"]["code"] == "publish.not_connected"
