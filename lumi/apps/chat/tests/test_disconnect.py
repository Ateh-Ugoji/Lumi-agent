"""The real ASGI handler: a client that hangs up stops the agent turn."""

import asyncio
import json

import pytest
from asgiref.sync import sync_to_async
from django.core.asgi import get_asgi_application
from django.db import connections

from apps.accounts.models import AuthToken, User
from apps.chat import sse
from apps.core import agent_runtime as runtime
from apps.profiles import services
from apps.profiles.models import SocialProfile
from lumi_ai.agent.result import SSEEvent


class SlowRuntime:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def stream_turn(self, profile_id, message):
        yield SSEEvent("tool_start", {"tool": "t", "arguments": {}, "reason": None})
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        yield SSEEvent("done", {"content": "never", "tool_executions": []})


def _setup():
    user = User.objects.create_user("asgi@example.com")
    _, key = AuthToken.issue(user, name="asgi")
    hid = services.get_or_create_handle("x", "asgi", origin="profile")
    profile = SocialProfile.objects.create(user=user, handle_id=hid)
    return key, profile.pk


@pytest.mark.django_db(transaction=True)
async def test_client_disconnect_cancels_the_turn():
    key, profile_id = await sync_to_async(_setup)()
    fake = SlowRuntime()
    runtime.set_runtime(fake)
    sent, disconnect = [], asyncio.Event()
    body = json.dumps({"profile_id": profile_id, "message": "hi"}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat/stream",
        "raw_path": b"/api/v1/chat/stream",
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1),
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", f"Token {key}".encode()),
        ],
    }
    sent_request = False

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    app = asyncio.ensure_future(get_asgi_application()(scope, receive, send))
    try:
        await asyncio.wait_for(fake.started.wait(), 10)
        assert sent[0]["status"] == 200
        assert any(b"tool_start" in m.get("body", b"") for m in sent)
        disconnect.set()
        await asyncio.wait_for(fake.cancelled.wait(), 10)
        await asyncio.wait_for(asyncio.shield(app), 10)
        assert not sse.ACTIVE
    finally:
        runtime.set_runtime(None)
        app.cancel()
        await asyncio.gather(app, return_exceptions=True)
        await sync_to_async(connections.close_all)()
