from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from apps.connections.clients.credits import CreditEntry, CreditMeter
from apps.connections.clients.xpoz import (
    USER_SEARCH,
    XpozClient,
    user_search_credits,
)
from apps.connections.config import ConnectionsConfig
from apps.connections.errors import (
    BudgetExceeded,
    LiveDisabled,
    ProviderAuthError,
    ProviderRequestError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedPlatform,
    ValidationFailed,
)

from .fakes import Recorder, fixture, json_response

KEY1, KEY2 = "xpoz-key-one-NOT-REAL", "xpoz-key-two-NOT-REAL"


async def no_sleep(_: float) -> None:
    return None


class MemoryCredits:
    def __init__(self) -> None:
        self.entries: list[CreditEntry] = []

    async def record(self, entry: CreditEntry) -> None:
        self.entries.append(entry)


def make(
    rec: Recorder,
    *,
    live: str = "true",
    budget: str = "10",
    keys: tuple[str, ...] = (KEY1,),
    extra_env: dict[str, str] | None = None,
    **kw,
):
    env = {"XPOZ_LIVE_ENABLED": live, "XPOZ_RUN_CREDIT_BUDGET": budget}
    env.update(extra_env or {})
    if len(keys) > 0:
        env["XPOZ_API_KEY"] = keys[0]
    if len(keys) > 1:
        env["XPOZ_API_KEY_2"] = keys[1]
    return XpozClient(
        ConnectionsConfig.from_env(env), transport=rec.transport, sleep=no_sleep, **kw
    )


def users_ok(request: httpx.Request) -> httpx.Response:
    return json_response("xpoz_users_x.json")


async def test_live_switch_off_raises_before_anything_else() -> None:
    rec = Recorder(users_ok)
    c = make(rec, live="false")
    with pytest.raises(LiveDisabled):
        await c.search_users("x", "naval")
    assert rec.requests == [] and c.meter.spent == 0


async def test_default_config_never_calls_xpoz() -> None:
    rec = Recorder(users_ok)
    c = XpozClient(
        ConnectionsConfig.from_env({"XPOZ_API_KEY": KEY1}), transport=rec.transport
    )
    with pytest.raises(LiveDisabled):
        await c.user_posts_page("x", "ateh")
    assert rec.requests == []


async def test_no_key_is_unavailable_and_costs_nothing() -> None:
    rec = Recorder(users_ok)
    c = make(rec, keys=())
    with pytest.raises(ProviderUnavailable):
        await c.search_users("x", "naval")
    assert rec.requests == [] and c.meter.spent == 0


def test_prices_follow_the_pricing_page() -> None:
    assert {p: user_search_credits(p) for p in USER_SEARCH} == {
        "x": 2,
        "instagram": 12,
        "tiktok": 5,
        "reddit": 2,
    }
    with pytest.raises(UnsupportedPlatform):
        user_search_credits("linkedin")


async def test_search_users_sends_bearer_query_param_and_fields_per_platform() -> None:
    rec = Recorder(users_ok)
    c = make(rec)
    page = await c.search_users("x", "@naval")
    req = rec.requests[0]
    assert req.url.path == "/api/data/twitter/users/live"
    assert req.url.params["q"] == "naval"
    assert "followersCount" in req.url.params["fields"]
    assert req.headers["authorization"] == f"Bearer {KEY1}"
    assert page.credits == 2 and len(page.results) == 3 and c.meter.spent == 2

    rec2 = Recorder(lambda r: json_response("xpoz_users_instagram.json"))
    await make(rec2, budget="12").search_users("instagram", "ateh")
    assert rec2.requests[0].url.path == "/api/data/instagram/users/live"
    assert rec2.requests[0].url.params["name"] == "ateh"


async def test_budget_stops_at_the_exact_credit() -> None:
    rec = Recorder(users_ok)
    c = make(rec, budget="10")
    for _ in range(5):
        await c.search_users("x", "naval")  # 5 x 2 = 10
    assert c.meter.spent == 10 and c.meter.remaining == 0
    with pytest.raises(BudgetExceeded) as caught:
        await c.search_users("x", "naval")
    assert (caught.value.spent, caught.value.budget) == (10, 10)
    assert len(rec.requests) == 5


async def test_a_call_that_does_not_fit_is_refused_even_with_credits_left() -> None:
    rec = Recorder(lambda r: json_response("xpoz_users_instagram.json"))
    c = make(rec, budget="11")
    with pytest.raises(BudgetExceeded):
        await c.search_users("instagram", "ateh")  # costs 12, only 11 allowed
    assert rec.requests == [] and c.meter.spent == 0


async def test_zero_budget_blocks_every_call() -> None:
    rec = Recorder(users_ok)
    with pytest.raises(BudgetExceeded):
        await make(rec, budget="0").search_users("x", "naval")
    assert rec.requests == []


async def test_a_shared_meter_spans_clients_of_one_run() -> None:
    meter = CreditMeter(4, provider="xpoz")
    rec = Recorder(users_ok)
    a, b = make(rec, meter=meter), make(rec, meter=meter)
    await a.search_users("x", "naval")
    await b.search_users("x", "naval")
    with pytest.raises(BudgetExceeded):
        await a.search_users("x", "naval")


async def test_key_rotates_on_401_402_403_and_is_charged_once() -> None:
    codes = {KEY1: 402}

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["authorization"].removeprefix("Bearer ")
        if key in codes:
            return httpx.Response(codes[key], json=fixture("xpoz_error_402.json"))
        return json_response("xpoz_users_x.json")

    rec = Recorder(handler)
    ledger = MemoryCredits()
    c = make(rec, keys=(KEY1, KEY2), ledger=ledger, run_id="run-1")
    await c.search_users("x", "naval")
    assert c.meter.spent == 2
    assert [e.key_slot for e in ledger.entries] == [2]
    assert ledger.entries[0].credits == 2 and ledger.entries[0].run_id == "run-1"
    assert KEY1 not in repr(ledger.entries) and KEY2 not in repr(ledger.entries)
    await c.search_users("x", "naval")  # key 1 is remembered as dead: one request only
    assert len(rec.requests) == 3


@pytest.mark.parametrize("status", [401, 403])
async def test_all_keys_rejected_is_an_auth_error(status: int) -> None:
    rec = Recorder(
        lambda r: httpx.Response(status, json=fixture("xpoz_error_403_trial.json"))
    )
    c = make(rec, keys=(KEY1, KEY2))
    with pytest.raises(ProviderAuthError) as caught:
        await c.search_users("x", "naval")
    assert KEY1 not in str(caught.value) and KEY2 not in str(caught.value)
    with pytest.raises(ProviderAuthError):  # every slot is dead now
        await c.search_users("x", "naval")
    assert len(rec.requests) == 2


async def test_all_keys_out_of_credits_is_budget_exceeded() -> None:
    rec = Recorder(lambda r: httpx.Response(402, json=fixture("xpoz_error_402.json")))
    with pytest.raises(BudgetExceeded):
        await make(rec, keys=(KEY1, KEY2)).search_users("x", "naval")


async def test_429_and_5xx_are_typed_and_5xx_retries_once() -> None:
    rec = Recorder(lambda r: httpx.Response(429, headers={"retry-after": "3"}))
    with pytest.raises(RateLimited) as caught:
        await make(rec).search_users("x", "naval")
    assert caught.value.retry_after_seconds == 3.0 and len(rec.requests) == 2

    rec2 = Recorder(
        lambda r: httpx.Response(500, json={"success": False, "message": "boom"})
    )
    with pytest.raises(ProviderUnavailable):
        await make(rec2).search_users("x", "naval")
    assert len(rec2.requests) == 2


async def test_a_transient_5xx_then_success_is_not_charged_twice() -> None:
    answers = [httpx.Response(502), json_response("xpoz_users_x.json")]
    rec = Recorder(lambda r: answers.pop(0))
    c = make(rec)
    await c.search_users("x", "naval")
    assert c.meter.spent == 2


async def test_user_posts_page_validates_the_username_and_formats_since() -> None:
    rec = Recorder(lambda r: json_response("xpoz_user_posts_page1.json"))
    c = make(rec)
    page = await c.user_posts_page(
        "x", "@Ateh", since=datetime(2026, 10, 1, 12, tzinfo=UTC)
    )
    req = rec.requests[0]
    assert req.url.path == "/api/data/twitter/posts/users/Ateh/live"
    assert req.url.params["since"] == "2026-10-01"
    assert page.has_more and page.next_cursor == "xcur_2" and page.credits == 2
    await c.user_posts_page("x", "ateh", cursor="xcur_2", since=date(2026, 10, 2))
    assert rec.requests[1].url.params["cursor"] == "xcur_2"
    for bad in ("../admin", "a b", "", "x" * 16):
        with pytest.raises(ValidationFailed):
            await c.user_posts_page("x", bad)
    assert len(rec.requests) == 2


async def test_search_posts_uses_the_posts_endpoint() -> None:
    rec = Recorder(lambda r: json_response("xpoz_user_posts_page1.json"))
    await make(rec).search_posts("x", " ai agents ")
    assert rec.requests[0].url.path == "/api/data/twitter/posts/live"
    assert rec.requests[0].url.params["q"] == "ai agents"


async def test_posts_endpoints_follow_the_platform_and_its_price() -> None:
    rec = Recorder(lambda r: json_response("xpoz_posts_instagram.json"))
    c = make(rec, budget="40")
    page = await c.search_posts("instagram", "lagos food")
    assert rec.requests[0].url.path == "/api/data/instagram/posts/live"
    assert rec.requests[0].url.params["q"] == "lagos food"
    assert page.credits == 12 and c.meter.spent == 12
    await c.user_posts_page("instagram", "lagos_eats")
    assert rec.requests[1].url.path == "/api/data/instagram/posts/users/lagos_eats/live"
    # ``since`` is X-only: the path would reject it, so it is never sent.
    assert "since" not in rec.requests[1].url.params
    rec2 = Recorder(lambda r: json_response("xpoz_posts_tiktok.json"))
    tiktok = make(rec2)
    await tiktok.search_posts("tiktok", "freelance")
    assert rec2.requests[0].url.path == "/api/data/tiktok/posts/live"
    assert tiktok.meter.spent == 5


async def test_facebook_and_linkedin_have_no_post_endpoint() -> None:
    rec = Recorder(users_ok)
    c = make(rec)
    for platform in ("facebook", "linkedin"):
        with pytest.raises(UnsupportedPlatform):
            await c.search_posts(platform, "ai")
        with pytest.raises(UnsupportedPlatform):
            await c.user_posts_page(platform, "ateh")
    assert rec.requests == [] and c.meter.spent == 0


async def test_blank_query_and_unsupported_platform_cost_nothing() -> None:
    rec = Recorder(users_ok)
    c = make(rec)
    with pytest.raises(ValidationFailed):
        await c.search_users("x", "  @ ")
    with pytest.raises(UnsupportedPlatform):
        await c.search_users("linkedin", "ateh")
    assert rec.requests == [] and c.meter.spent == 0


async def test_malformed_answers_are_request_errors() -> None:
    for response in (
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json=[1]),
        httpx.Response(200, json={"results": "x"}),
    ):
        rec = Recorder(lambda r, resp=response: resp)
        with pytest.raises(ProviderRequestError):
            await make(rec).search_users("x", "naval")


async def test_empty_results_are_a_valid_page() -> None:
    rec = Recorder(
        lambda r: httpx.Response(200, json={"results": [], "has_more": False})
    )
    page = await make(rec).search_users("x", "zzzz")
    assert page.results == () and page.has_more is False


async def test_has_more_without_a_cursor_is_not_followed() -> None:
    rec = Recorder(
        lambda r: httpx.Response(200, json={"results": [], "has_more": True})
    )
    assert (await make(rec).search_users("x", "naval")).has_more is False


async def test_a_platform_override_gives_instagram_its_own_budget() -> None:
    rec = Recorder(lambda r: json_response("xpoz_users_instagram.json"))
    c = make(rec, budget="2", extra_env={"XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM": "12"})
    await c.search_users("instagram", "ateh")  # 12, from its own meter
    assert c.meter_for("instagram").spent == 12 and c.meter.spent == 0
    with pytest.raises(BudgetExceeded):
        await c.search_users("instagram", "ateh")  # its 12 are used up
    assert len(rec.requests) == 1


async def test_a_platform_override_does_not_open_the_shared_budget() -> None:
    rec = Recorder(users_ok)
    c = make(rec, budget="2", extra_env={"XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM": "12"})
    await c.search_users("x", "naval")  # 2 from the shared meter
    with pytest.raises(BudgetExceeded):
        await c.search_users("x", "naval")
    assert len(rec.requests) == 1


async def test_a_platform_can_be_closed_while_the_others_stay_open() -> None:
    rec = Recorder(users_ok)
    c = make(rec, budget="12", extra_env={"XPOZ_RUN_CREDIT_BUDGET_X": "0"})
    with pytest.raises(BudgetExceeded):
        await c.search_users("x", "naval")
    assert rec.requests == []


async def test_the_default_budget_pays_for_one_instagram_search_and_no_more() -> None:
    rec = Recorder(lambda r: json_response("xpoz_users_instagram.json"))
    c = XpozClient(
        ConnectionsConfig.from_env({"XPOZ_LIVE_ENABLED": "true", "XPOZ_API_KEY": KEY1}),
        transport=rec.transport,
        sleep=no_sleep,
    )
    await c.search_users("instagram", "ateh")
    with pytest.raises(BudgetExceeded):
        await c.search_users("x", "naval")
    assert len(rec.requests) == 1
