from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from apps.connections.clients.xpoz import XpozClient
from apps.connections.config import ConnectionsConfig
from apps.connections.errors import BudgetExceeded, LiveDisabled, UnsupportedPlatform
from apps.connections.socialdata import XpozSocialData

from .fakes import Recorder, fixture, json_response


async def no_sleep(_: float) -> None:
    return None


def build(
    handler, *, live="true", budget="20"
) -> tuple[XpozSocialData, Recorder, XpozClient]:
    rec = Recorder(handler)
    config = ConnectionsConfig.from_env(
        {
            "XPOZ_API_KEY": "k",
            "XPOZ_LIVE_ENABLED": live,
            "XPOZ_RUN_CREDIT_BUDGET": budget,
        }
    )
    client = XpozClient(config, transport=rec.transport, sleep=no_sleep)
    return XpozSocialData(client), rec, client


def paged(*names: str):
    pages = list(names)
    return lambda r: httpx.Response(200, json=fixture(pages.pop(0)))


async def test_fetch_user_posts_pages_sorts_and_limits() -> None:
    data, rec, _ = build(
        paged("xpoz_user_posts_page1.json", "xpoz_user_posts_page2.json")
    )
    posts = await data.fetch_user_posts("x", "ateh", None, 100)
    assert [p.external_id for p in posts] == ["201", "200", "199", "198", "197", "120"]
    assert rec.requests[1].url.params["cursor"] == "xcur_2"
    limited, rec2, _ = build(paged("xpoz_user_posts_page1.json"))
    assert len(await limited.fetch_user_posts("x", "ateh", None, 2)) == 2
    assert len(rec2.requests) == 1


async def test_since_filters_old_posts_and_stops_paging() -> None:
    data, rec, _ = build(
        paged("xpoz_user_posts_page1.json", "xpoz_user_posts_page2.json")
    )
    posts = await data.fetch_user_posts("x", "ateh", datetime(2026, 10, 15), 100)
    assert "120" not in {p.external_id for p in posts} and len(posts) == 5
    assert rec.requests[0].url.params["since"] == "2026-10-15"


async def test_budget_cut_mid_run_returns_what_was_read() -> None:
    data, rec, _ = build(
        paged("xpoz_user_posts_page1.json", "xpoz_user_posts_page2.json"), budget="2"
    )
    posts = await data.fetch_user_posts("x", "ateh", None, 100)
    assert len(posts) == 3 and len(rec.requests) == 1


async def test_budget_cut_before_any_data_still_raises() -> None:
    data, rec, _ = build(paged("xpoz_user_posts_page1.json"), budget="0")
    with pytest.raises(BudgetExceeded):
        await data.fetch_user_posts("x", "ateh", None, 5)
    assert rec.requests == []


async def test_live_switch_off_raises_and_never_calls() -> None:
    data, rec, _ = build(paged("xpoz_user_posts_page1.json"), live="false")
    with pytest.raises(LiveDisabled):
        await data.fetch_user_posts("x", "ateh", None, 5)
    assert rec.requests == []


@pytest.mark.parametrize("platform", ["linkedin", "facebook"])
async def test_networks_without_a_post_endpoint_refuse_without_spending(
    platform: str,
) -> None:
    data, rec, client = build(paged("xpoz_user_posts_page1.json"))
    with pytest.raises(UnsupportedPlatform):
        await data.fetch_user_posts(platform, "ateh", None, 5)  # type: ignore[arg-type]
    with pytest.raises(UnsupportedPlatform):
        await data.search_posts(platform, "ai", 5)  # type: ignore[arg-type]
    assert rec.requests == [] and client.meter.spent == 0


async def test_instagram_search_maps_its_own_fields() -> None:
    data, rec, client = build(lambda r: json_response("xpoz_posts_instagram.json"), budget="12")
    posts = await data.search_posts("instagram", "lagos food", 5)
    assert rec.requests[0].url.path == "/api/data/instagram/posts/live"
    assert [p.text for p in posts] == [
        "Three spots in Yaba you have not tried yet",
        "The jollof ranking nobody asked for",
    ]
    first = posts[0]
    assert first.platform == "instagram" and first.author_handle == "lagos_eats"
    assert first.metrics.likes == 4210 and first.metrics.views == 91200
    assert first.url == "https://www.instagram.com/p/DPq8mQ9jKxR/"
    assert first.author_avatar_url and first.kind == "original"
    # No codeUrl on the second row: the permalink is built from the handle and the id.
    assert posts[1].url == "https://www.instagram.com/yaba_bites/p/3430102783691229106/"
    assert client.meter.spent == 12


async def test_instagram_timeline_works_and_skips_the_since_param() -> None:
    data, rec, _ = build(lambda r: json_response("xpoz_posts_instagram.json"), budget="12")
    posts = await data.fetch_user_posts(
        "instagram", "lagos_eats", datetime(2026, 10, 20), 10
    )
    assert len(posts) == 2 and rec.requests[0].url.params.get("since") is None
    assert rec.requests[0].url.path == "/api/data/instagram/posts/users/lagos_eats/live"


async def test_tiktok_search_maps_description_and_play_count() -> None:
    data, rec, _ = build(lambda r: json_response("xpoz_posts_tiktok.json"))
    (post,) = await data.search_posts("tiktok", "freelance", 5)
    assert rec.requests[0].url.path == "/api/data/tiktok/posts/live"
    assert post.text == "How we priced our first retainer #freelance"
    assert post.metrics.views == 410000 and post.metrics.likes == 18200
    assert post.url == "https://www.tiktok.com/@builtinlagos/video/7419203847562910001"


async def test_limit_zero_spends_nothing() -> None:
    data, rec, _ = build(paged("xpoz_user_posts_page1.json"))
    assert await data.fetch_user_posts("x", "ateh", None, 0) == []
    assert await data.search_posts("x", "ai", 0) == []
    assert await data.search_users("x", "ai", 0) == []
    assert rec.requests == []


async def test_search_users_maps_each_platform() -> None:
    data, _, _ = build(lambda r: json_response("xpoz_users_x.json"))
    users = await data.search_users("x", "naval", 10)
    assert [u.handle for u in users] == ["naval", "notnaval", "navalfan"]
    assert users[0].followers == 2_500_000 and users[0].display_name == "Naval"
    assert users[2].followers is None and users[2].display_name is None

    ig, _, _ = build(lambda r: json_response("xpoz_users_instagram.json"), budget="12")
    assert (await ig.search_users("instagram", "ateh", 5))[0].followers == 900
    tt, _, _ = build(lambda r: json_response("xpoz_users_tiktok.json"))
    assert (await tt.search_users("tiktok", "ateh", 5))[0].display_name == "Ateh TT"
    assert len(await data.search_users("x", "naval", 2)) == 2


async def test_reddit_is_not_a_socialdata_platform() -> None:
    data, rec, _ = build(lambda r: json_response("xpoz_users_reddit.json"))
    with pytest.raises(UnsupportedPlatform):
        await data.search_users("reddit", "ateh", 5)  # type: ignore[arg-type]
    assert rec.requests == []


async def test_get_user_is_an_exact_case_insensitive_match() -> None:
    data, _, client = build(lambda r: json_response("xpoz_users_x.json"))
    user = await data.get_user("x", "@NAVAL")
    assert user is not None and user.handle == "naval"
    assert client.meter.spent == 2
    assert await data.get_user("x", "nav") is None


async def test_search_posts_maps_and_limits() -> None:
    data, _, _ = build(paged("xpoz_user_posts_page1.json"))
    posts = await data.search_posts("x", "ai agents", 2)
    assert len(posts) == 2 and posts[0].source == "xpoz"
