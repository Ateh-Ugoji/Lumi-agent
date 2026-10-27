"""``POST /chat/stream`` through the real ASGI application on a real socket.

A buffering server would hold the first event until the turn ends. The fake turn here does not
end until the client has read the first event, so a buffered response makes the test time out.
"""

import asyncio
import json

import httpx
import pytest
import uvicorn
from asgiref.sync import sync_to_async
from django.db import connections

from apps.accounts.models import AuthToken
from apps.core import agent_runtime as runtime
from lumi_ai.agent.result import SSEEvent

pytestmark = pytest.mark.django_db(transaction=True)

#: Shape only, never used to call a provider or to encrypt anything real.
DUMMY_FERNET = "ZmFrZS1mYWtlLWZha2UtZmFrZS1mYWtlLWZha2UtMDA="


@pytest.fixture(autouse=True)
def own_keys(monkeypatch, settings):
    """``config.asgi`` runs the production startup check on import: give it its own environment.

    The check stays on (``KEYS_ENFORCE_REQUIRED = True``), so this test passes with no keys in
    the shell and still proves the application starts when the required ones are present.
    """
    monkeypatch.setenv("GROQ_API_KEY", "dummy-not-called")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", DUMMY_FERNET)
    settings.KEYS_ENFORCE_REQUIRED = True


def test_the_startup_check_passes_with_the_required_keys_present():
    from apps.core import startup

    startup.check()


class GatedRuntime:
    """Yields one event, then waits until the test says the client has seen it."""

    def __init__(self):
        self.gate = None
        self.turn_finished = False

    async def stream_turn(self, profile_id, message):
        yield SSEEvent(
            "tool_start", {"tool": "get_analytics", "arguments": {}, "reason": "r"}
        )
        await asyncio.wait_for(self.gate.wait(), timeout=5)
        yield SSEEvent("done", {"content": "listo", "tool_executions": []})
        self.turn_finished = True

    async def run_turn(self, profile_id, message):
        raise NotImplementedError


@pytest.fixture
def gated():
    fake = GatedRuntime()
    runtime.set_runtime(fake)
    yield fake
    runtime.set_runtime(None)


async def serve():
    from config.asgi import application

    config = uvicorn.Config(
        application, host="127.0.0.1", port=0, log_level="warning", lifespan="off"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


async def test_sse_arrives_event_by_event_not_buffered(owner, profile, gated, settings):
    settings.ALLOWED_HOSTS = ["*"]
    gated.gate = asyncio.Event()
    _, key = await sync_to_async(AuthToken.issue)(owner, name="asgi")
    server, task, port = await serve()
    try:
        async with (
            httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=10
            ) as client,
            client.stream(
                "POST",
                "/api/v1/chat/stream",
                json={"profile_id": profile.pk, "message": "hola"},
                headers={"Authorization": f"Token {key}"},
            ) as response,
        ):
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.aiter_lines()
            first = None
            async for line in lines:
                if line.startswith("data: "):
                    first = json.loads(line[len("data: ") :])
                    break
            # The turn is still waiting on the gate: the first event came out early.
            assert first["type"] == "tool_start"
            assert not gated.turn_finished
            gated.gate.set()
            rest = [
                json.loads(line[len("data: ") :])
                async for line in lines
                if line.startswith("data: ")
            ]
        assert [e["type"] for e in rest] == ["done"]
        assert gated.turn_finished
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        # Free the connection the view used so the test database can be dropped.
        await sync_to_async(connections.close_all)()
