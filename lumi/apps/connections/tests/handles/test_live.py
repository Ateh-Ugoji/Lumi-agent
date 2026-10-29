from __future__ import annotations

import httpx

from apps.connections.clients.xpoz import USER_SEARCH, XpozClient
from apps.connections.config import ConnectionsConfig
from apps.connections.handles.live import XpozHandleLive, row_from_user
from apps.connections.handles.service import HandleSearch

from ..fakes import Recorder, fixture
from .fakes import Clock, MemoryHandleStore


def live_for(fixture_name: str, budget: str = "20") -> tuple[XpozHandleLive, Recorder]:
    rec = Recorder(lambda r: httpx.Response(200, json=fixture(fixture_name)))
    config = ConnectionsConfig.from_env(
        {
            "XPOZ_API_KEY": "k",
            "XPOZ_LIVE_ENABLED": "true",
            "XPOZ_RUN_CREDIT_BUDGET": budget,
        }
    )
    return XpozHandleLive(XpozClient(config, transport=rec.transport)), rec


async def test_supports_exactly_the_xpoz_user_search_platforms() -> None:
    live, _ = live_for("xpoz_users_x.json")
    assert {
        p
        for p in ("x", "instagram", "tiktok", "reddit", "linkedin")
        if live.supports(p)
    } == set(USER_SEARCH)


async def test_x_rows_keep_unknown_followers_as_none() -> None:
    live, _ = live_for("xpoz_users_x.json")
    rows = await live.search("x", "naval")
    assert [r.handle for r in rows] == ["naval", "notnaval", "navalfan"]
    assert rows[0].followers == 2_500_000 and rows[2].followers is None
    assert rows[2].display_name == "" and all(r.source == "live" for r in rows)


async def test_each_platform_reads_its_own_field_names() -> None:
    cases = {
        "instagram": ("xpoz_users_instagram.json", "ateh.ig", 900, "Ateh"),
        "tiktok": ("xpoz_users_tiktok.json", "ateh.tt", 77, "Ateh TT"),
        "reddit": ("xpoz_users_reddit.json", "ateh_r", None, ""),
    }
    for platform, (name, handle, followers, display) in cases.items():
        live, _ = live_for(name)
        (found,) = await live.search(platform, "ateh")
        assert (found.handle, found.followers, found.display_name) == (
            handle,
            followers,
            display,
        )


def test_rows_without_a_handle_are_dropped() -> None:
    spec = USER_SEARCH["x"]
    assert row_from_user("x", spec, {"name": "No handle"}) is None
    assert row_from_user("x", spec, {"username": "  "}) is None
    assert row_from_user("x", spec, {"username": "@Ab"}).handle == "Ab"


async def test_end_to_end_with_the_service_spends_two_credits_once() -> None:
    live, rec = live_for("xpoz_users_x.json")
    svc = HandleSearch(MemoryHandleStore(), live, ttl_minutes=60, clock=Clock())
    first = await svc.search("naval")
    await svc.search("naval")
    assert len(rec.requests) == 1 and first.results[0].handle == "naval"
