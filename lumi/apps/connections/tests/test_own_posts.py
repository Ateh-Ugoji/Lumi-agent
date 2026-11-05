from __future__ import annotations

from datetime import UTC, datetime

import httpx

from apps.connections.clients.pfm import PfmClient
from apps.connections.config import ConnectionsConfig
from apps.connections.own_posts import collect_own_posts

from .fakes import Recorder, fixture


async def no_sleep(_: float) -> None:
    return None


def feed(rec_pages: list[str]) -> tuple[PfmClient, Recorder]:
    pages = list(rec_pages)
    rec = Recorder(lambda r: httpx.Response(200, json=fixture(pages.pop(0))))
    config = ConnectionsConfig.from_env({"PFM_JWT_TOKEN": "t"})
    return PfmClient(config, transport=rec.transport, sleep=no_sleep), rec


PAGES = ["pfm_feed_x_page1.json", "pfm_feed_x_page2.json"]


async def test_pages_until_the_end_and_counts_skipped() -> None:
    client, rec = feed(PAGES)
    result = await collect_own_posts(client, "sa_1", handle="ateh", limit=100)
    assert result.pages == 2 and result.stopped == "end" and len(result.posts) == 5
    assert rec.requests[1].url.params["cursor"] == "pgn_next_1"


async def test_stops_at_the_limit_without_reading_more_pages() -> None:
    client, rec = feed(PAGES)
    result = await collect_own_posts(client, "sa_1", handle="ateh", limit=2)
    assert (
        len(result.posts) == 2 and result.stopped == "limit" and len(rec.requests) == 1
    )


async def test_since_accepts_naive_datetimes_and_stops_at_old_posts() -> None:
    client, _ = feed(PAGES)
    result = await collect_own_posts(
        client, "sa_1", handle="ateh", limit=100, since=datetime(2026, 10, 15)
    )
    assert result.stopped == "since"
    assert {p.external_id for p in result.posts} == {"101", "100", "99"}


async def test_max_pages_is_a_hard_stop() -> None:
    client, rec = feed(PAGES)
    result = await collect_own_posts(
        client, "sa_1", handle="ateh", limit=100, max_pages=1
    )
    assert result.stopped == "max_pages" and len(rec.requests) == 1


async def test_unusable_items_are_skipped_not_fatal() -> None:
    bad = {
        "data": [
            {
                "platform": "x",
                "platform_post_id": "1",
                "caption": "",
                "posted_at": "2026-10-20T10:00:00Z",
            }
        ],
        "meta": {"cursor": None, "has_more": False},
    }
    rec = Recorder(lambda r: httpx.Response(200, json=bad))
    client = PfmClient(
        ConnectionsConfig.from_env({"PFM_JWT_TOKEN": "t"}),
        transport=rec.transport,
        sleep=no_sleep,
    )
    result = await collect_own_posts(
        client, "sa_1", handle=None, limit=10, since=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert result.posts == () and result.skipped == 1
