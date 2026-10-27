"""Simulated providers for the e2e harness and the journey test.

Everything here answers from the recorded fixtures in ``apps/connections/tests/fixtures`` through
``httpx.MockTransport``. No request leaves the process, no key is needed, and the values are the
fake ones already used by the unit tests.

* ``install()`` swaps ``accounts.make_provider`` and ``accounts.make_pfm``.
* ``FakeRuntime`` stands in for the agent (``apps.core.agent_runtime.set_runtime``).
* ``pfm_consent`` is the page the PFM authorize URL would show; it flips the simulated PFM account on.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from asgiref.sync import sync_to_async
from django.http import HttpResponse, HttpResponseRedirect

from apps.connections import accounts
from apps.connections.clients.pfm import PfmClient
from apps.connections.providers.registry import build_provider
from apps.connections.tests.fakes import fixture
from lumi_ai.agent.result import SSEEvent

PFM_ACCOUNT_ID = "sa_sim_1"


@dataclass
class PfmWorld:
    """What the simulated PFM account holds."""

    connected: bool = False
    platform: str = "instagram"
    feed_calls: int = 0
    meta_pages: int = 2
    calls: list[str] = field(default_factory=list)


WORLD = PfmWorld()


def _meta_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/oauth/access_token"):
        name = (
            "meta_long_token.json"
            if httpx.QueryParams(request.content.decode()).get("grant_type")
            else "meta_short_token.json"
        )
        return httpx.Response(200, json=fixture(name))
    if path.endswith("/me/accounts"):
        body = fixture("meta_accounts.json")
        return httpx.Response(
            200, json={**body, "data": body["data"][: WORLD.meta_pages]}
        )
    if path.endswith("/me"):
        return httpx.Response(200, json=fixture("meta_me.json"))
    if path.endswith("/feed") and request.method == "POST":
        return httpx.Response(200, json=fixture("meta_feed.json"))
    if path.endswith("/posts"):
        return httpx.Response(200, json={"data": []})
    return httpx.Response(404, json={"error": {"message": f"sim: no route {path}"}})


def _pfm_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    WORLD.calls.append(f"{request.method} {path}")
    if path == "/v1/social-accounts/auth-url":
        body = json.loads(request.content or b"{}")
        return httpx.Response(
            200,
            json={
                "platform": body.get("platform", "instagram"),
                "url": "https://api.postforme.dev/oauth/connect/SIM-STATE",
            },
        )
    if path == "/v1/social-accounts" and request.method == "GET":
        if not WORLD.connected:
            return httpx.Response(200, json={"data": [], "meta": {"total": 0}})
        row = dict(fixture("pfm_accounts.json")["data"][0])
        row["id"] = PFM_ACCOUNT_ID
        row["platform"] = WORLD.platform
        row["external_id"] = request.url.params.get("external_id", row["external_id"])
        for secret in ("access_token", "refresh_token"):
            row.pop(secret, None)
        return httpx.Response(200, json={"data": [row], "meta": {"total": 1}})
    if path.endswith("/disconnect"):
        WORLD.connected = False
        return httpx.Response(
            200,
            json={
                "id": PFM_ACCOUNT_ID,
                "platform": WORLD.platform,
                "status": "disconnected",
            },
        )
    return httpx.Response(404, json={"message": f"sim: no route {path}"})


def _blocked(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"sim: {request.url.host} is blocked in the e2e harness")


def install() -> Callable[[], None]:
    """Route provider and PFM calls to the simulation. Returns a function that undoes it."""
    original = (accounts.make_provider, accounts.make_pfm)

    def make_provider(name: str):
        handler = _meta_handler if name == "meta" else _blocked
        return build_provider(
            name, accounts.get_config(), transport=httpx.MockTransport(handler)
        )

    def make_pfm() -> PfmClient:
        return PfmClient(
            accounts.get_config(), transport=httpx.MockTransport(_pfm_handler)
        )

    accounts.make_provider, accounts.make_pfm = make_provider, make_pfm

    def undo() -> None:
        accounts.make_provider, accounts.make_pfm = original

    return undo


def pfm_consent(request):
    """Where the browser lands after "authorizing" on PFM: the account is now connected."""
    WORLD.connected = True
    WORLD.platform = request.GET.get("platform", "instagram")
    # PFM redirects to the FRONTEND page registered in its dashboard, not to the API.
    return HttpResponseRedirect(
        "http://localhost:3010/connections/pfm/callback?isSuccess=true&platform="
        + WORLD.platform
    )


def meta_pages(request):
    """Test hook: how many Pages the next Meta login returns (one page links to the profile)."""
    WORLD.meta_pages = int(request.GET.get("n", "2"))
    return HttpResponse("ok")


# --- the agent -----------------------------------------------------------------------------------


def _owner_of(profile_id: int):
    from apps.profiles.models import SocialProfile

    return SocialProfile.objects.select_related("user").get(pk=profile_id).user


class FakeRuntime:
    """A scripted agent. "connect" calls the real connect flow; anything else gets a canned answer."""

    async def run_turn(self, profile_id: int, message: str):
        from lumi_ai.agent.result import TurnResult

        events = [e async for e in self.stream_turn(profile_id, message)]
        done = events[-1].data
        return TurnResult(content=done["content"])

    async def scan_trends(self, profile_id, handles, min_likes) -> dict[str, Any]:
        return {"matches": [], "scanned": 0}

    async def generate_title(self, message: str) -> str | None:
        return None

    async def stream_turn(
        self, profile_id: int, message: str
    ) -> AsyncIterator[SSEEvent]:
        if re.search(r"conect|connect", message, re.IGNORECASE):
            user = await sync_to_async(_owner_of)(profile_id)
            url = await sync_to_async(accounts.start_connect)(user, "meta")
            args = {"platform": "facebook"}
            result = {
                "already_connected": False,
                "platform": "facebook",
                "connect_url": url,
                "handle": "",
            }
            yield SSEEvent("tool_start", {"tool": "connect_account", "arguments": args})
            yield SSEEvent("tool_done", {"tool": "connect_account", "sample_posts": []})
            yield SSEEvent(
                "done",
                {
                    "content": f"[Connect facebook]({url})",
                    "tool_executions": [
                        {
                            "name": "connect_account",
                            "arguments": args,
                            "sample_posts": [],
                            "result": result,
                        }
                    ],
                },
            )
            return
        yield SSEEvent(
            "done",
            {"content": f"Respuesta simulada a: {message}", "tool_executions": []},
        )
