from __future__ import annotations

import pytest

from apps.connections.errors import (
    BudgetExceeded,
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    RateLimited,
)
from apps.connections.handles.service import HandleSearch
from apps.connections.handles.types import CacheEntry, HandleRow

from .fakes import Clock, MemoryHandleStore, ScriptedLive, row


def build(live=None, store=None, ttl=60):
    clock = Clock()
    store = store or MemoryHandleStore()
    live = live or ScriptedLive(
        {"x": [row("naval", followers=100), row("navalfan", followers=3)]}
    )
    return HandleSearch(store, live, ttl_minutes=ttl, clock=clock), store, live, clock


async def test_short_queries_never_reach_live_or_store() -> None:
    svc, store, live, _ = build()
    for q in ("", "n", "@", " @n "):
        result = await svc.search(q)
        assert result.reason == "min_length" and result.results == ()
    assert live.calls == [] and store.entries == {}


async def test_first_search_goes_live_caches_and_remembers() -> None:
    svc, store, live, _ = build()
    result = await svc.search("@Nav")
    assert live.calls == [("x", "Nav")]
    assert result.live and not result.refreshed and result.reason is None
    assert [r.handle for r in result.results] == ["naval", "navalfan"]
    assert ("x", "nav") in store.entries and "x:naval" in store.rows


async def test_fresh_cache_skips_the_paid_call() -> None:
    svc, _, live, clock = build()
    await svc.search("nav")
    clock.advance(minutes=59)
    again = await svc.search("nav")
    assert len(live.calls) == 1 and not again.live
    assert [r.handle for r in again.results] == ["naval", "navalfan"]
    assert all(r.source == "cache" for r in again.results)


async def test_stale_cache_refreshes_live() -> None:
    svc, _, live, clock = build()
    await svc.search("nav")
    clock.advance(minutes=61)
    again = await svc.search("nav")
    assert len(live.calls) == 2 and again.live and again.refreshed


async def test_prefix_chain_reuses_a_fresh_longer_or_shorter_entry() -> None:
    svc, _, live, _ = build()
    await svc.search("na")
    longer = await svc.search("nav")
    assert len(live.calls) == 1  # "na" rows contain "nav", so the entry answers it
    assert [r.handle for r in longer.results] == ["naval", "navalfan"]
    none_match = await svc.search("naz")
    assert len(live.calls) == 2 and none_match.live  # no cached row contains "naz"


async def test_fresh_empty_search_is_a_negative_cache_with_a_reason() -> None:
    svc, _, live, _ = build(ScriptedLive({"x": []}))
    first = await svc.search("zzqq")
    assert first.live and first.results == ()
    second = await svc.search("zzqq")
    assert len(live.calls) == 1 and not second.live
    assert second.reason == "cache_exact" and second.platform_reasons == {
        "x": "cache_exact"
    }


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (LiveDisabled("off"), "live_disabled"),
        (BudgetExceeded("budget", spent=10, budget=10), "budget_exhausted"),
        (RateLimited("slow", retry_after_seconds=3), "rate_limited"),
        (ProviderAuthError("bad key"), "auth_error"),
        (ProviderUnavailable("down"), "provider_unavailable"),
    ],
)
async def test_live_failures_give_a_reason_and_are_not_cached(error, reason) -> None:
    svc, store, live, _ = build(ScriptedLive(error=error))
    result = await svc.search("nav")
    assert result.reason == reason and result.results == () and not result.live
    assert store.entries == {}
    live.error = None
    live.answers = {"x": [row("naval")]}
    retry = await svc.search("nav")
    assert retry.live and retry.results  # one outage did not hide the platform


async def test_unexpected_errors_are_not_swallowed() -> None:
    svc, _, _, _ = build(ScriptedLive(error=RuntimeError("bug")))
    with pytest.raises(RuntimeError):
        await svc.search("nav")


async def test_unsupported_platform_reason_and_other_platforms_still_answer() -> None:
    live = ScriptedLive({"x": [row("naval")]}, supported=("x",))
    svc, _, _, _ = build(live)
    result = await svc.search("nav", platforms="x,linkedin")
    assert result.platform_reasons == {"x": None, "linkedin": "unsupported"}
    assert result.reason == "unsupported" and [r.platform for r in result.results] == [
        "x"
    ]
    assert live.calls == [("x", "nav")]


async def test_profile_handles_lead_and_do_not_replace_the_live_call() -> None:
    store = MemoryHandleStore()
    store.profiles["x"] = ["navalrav"]
    svc, _, live, _ = build(store=store)
    result = await svc.search("nav")
    assert len(live.calls) == 1
    assert result.results[0].handle == "navalrav" and result.results[0].source == "db"


async def test_remembered_handles_are_a_head_start_only() -> None:
    store = MemoryHandleStore()
    await store.remember_live([row("navy", followers=7)])
    svc, _, live, _ = build(store=store)
    result = await svc.search("nav")
    assert len(live.calls) == 1
    assert {r.handle for r in result.results} == {"navy", "naval", "navalfan"}


async def test_stale_cache_rows_never_overwrite_fresh_live_data() -> None:
    store = MemoryHandleStore()
    clock = Clock()
    old = row("naval", followers=1, source="cache")
    await store.put_entry(
        CacheEntry(
            "x", "nav", clock() - __import__("datetime").timedelta(hours=5), (old,)
        )
    )
    svc = HandleSearch(
        store,
        ScriptedLive({"x": [row("naval", followers=999)]}),
        ttl_minutes=60,
        clock=clock,
    )
    result = await svc.search("nav")
    assert result.results[0].followers == 999 and result.refreshed


async def test_cache_rows_are_remembered_once_not_overwriting_known_ones() -> None:
    svc, store, _, _ = build()
    await svc.search("nav")
    store.rows["x:naval"] = row("naval", followers=555, source="cache")
    await svc.search("nav")  # fresh cache hit, row already known
    assert store.rows["x:naval"].followers == 555


async def test_context_words_rerank_but_never_reach_the_provider() -> None:
    live = ScriptedLive(
        {
            "x": [
                row("alpha", followers=1000),
                row("bravo", name="Naval Ravikant", followers=1),
            ]
        }
    )
    svc, _, _, _ = build(live)
    result = await svc.search("ra", context="thanks naval")
    assert result.results[0].handle == "bravo"
    assert live.calls == [("x", "ra")] and result.context == "thanks naval"


async def test_zero_ttl_never_reuses_the_cache() -> None:
    svc, _, live, _ = build(ttl=0)
    await svc.search("nav")
    await svc.search("nav")
    assert len(live.calls) == 2


async def test_multi_platform_search_spends_per_platform() -> None:
    live = ScriptedLive(
        {"x": [row("ateh")], "instagram": [row("ateh.ig", "instagram")]}
    )
    svc, _, _, _ = build(live)
    result = await svc.search("ateh", platforms="x,instagram")
    assert live.calls == [("x", "ateh"), ("instagram", "ateh")]
    assert {r.platform for r in result.results} == {"x", "instagram"}


async def test_a_profile_handle_that_is_also_remembered_keeps_the_db_label_and_the_richer_data() -> (
    None
):
    svc, store, _, _ = build()
    store.profiles["x"] = ["navalrav"]
    store.rows["x:navalrav"] = HandleRow(
        "NavalRav", "x", "Naval R", "https://i/a.png", 900, "cache"
    )
    result = await svc.search("naval")
    (found,) = [r for r in result.results if r.handle.lower() == "navalrav"]
    assert (found.source, found.display_name, found.followers) == ("db", "Naval R", 900)
