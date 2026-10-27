"""Port-backed tools, through the registry, with in-memory fakes."""

from __future__ import annotations

import pytest

from lumi_ai.ports import ActivityOut, AlertOut, ConnectLink, ProfileInfo
from lumi_ai.tests.fakes import (
    NOW,
    FakeLinks,
    FakeListening,
    FakePosts,
    FakeRepurpose,
    FakeRequests,
    FakeVoice,
    make_post,
)
from lumi_ai.tools import ToolContext, ToolDeps, build_registry
from lumi_ai.tools.data import compute_analytics

CTX = ToolContext(profile_id=1)


async def run(registry, name, **args):
    return await registry.call(
        CTX, name, {"reason": "answering the user's ask", **args}
    )


def test_a_tool_without_its_port_is_not_registered():
    assert build_registry(ToolDeps()).names == []
    registry = build_registry(ToolDeps(posts=FakePosts(), voice=FakeVoice()))
    assert registry.names == [
        "get_posts",
        "get_user_activity",
        "get_analytics",
        "get_voice_profile",
        "answer_style_questions",
    ]


def test_full_wiring_registers_the_twelve_port_backed_tools():
    deps = ToolDeps(
        posts=FakePosts(),
        voice=FakeVoice(),
        requests=FakeRequests(),
        listening=FakeListening(),
        repurpose=FakeRepurpose(),
        links=FakeLinks(ConnectLink(already_connected=False, url="https://x")),
        post_sync=object(),  # type: ignore[arg-type]
    )
    assert sorted(build_registry(deps).names) == sorted(
        [
            "get_posts", "get_user_activity", "get_analytics", "connect_account", "backfill_posts",
            "save_user_request", "get_voice_profile", "answer_style_questions",
            "start_listening", "stop_listening", "dismiss_alert", "submit_action",
        ]
    )  # fmt: skip


# --- data ------------------------------------------------------------------------


async def test_get_posts_only_returns_the_turn_profile_and_clamps_limit():
    posts = FakePosts([make_post(1), make_post(2, profile_id=9), make_post(3)])
    registry = build_registry(ToolDeps(posts=posts))
    out = await run(registry, "get_posts", profile_id=9, limit=1000)
    assert [p["id"] for p in out["posts"]] == [1, 3]


async def test_get_user_activity_filters_kind():
    act = [
        ActivityOut(1, 1, "x", "reply", "my take", NOW),
        ActivityOut(2, 1, "x", "retweet", "their words", NOW),
    ]
    registry = build_registry(ToolDeps(posts=FakePosts(activity=act)))
    assert (await run(registry, "get_user_activity", kind="reply"))["count"] == 1
    assert (await run(registry, "get_user_activity"))["count"] == 2


def test_analytics_keeps_unreported_metrics_null_not_zero():
    out = compute_analytics([make_post(1, views=None, likes=None)], 28)
    assert out["total_impressions"] is None and out["engagement_rate"] is None
    assert out["is_live_data"] is False and out["top_posts"] == []


def test_analytics_aggregates_reported_metrics():
    posts = [
        make_post(1, "a", views=1000, likes=50),
        make_post(2, "b", views=3000, likes=150, kind="quote"),
        make_post(3, "c", views=None, likes=None),
    ]
    out = compute_analytics(posts, 28)
    assert out["total_impressions"] == 4000 and out["total_likes"] == 200
    assert out["posts_in_window"] == 3 and out["posts_with_metrics"] == 3
    assert out["top_posts"][0]["id"] == 2
    assert {a["label"]: a["pct"] for a in out["allocation"]} == {
        "quote": 75.0,
        "original": 25.0,
    }
    assert out["median_impressions"] == 2000


async def test_get_analytics_with_no_posts_says_so_and_estimates_nothing():
    registry = build_registry(ToolDeps(posts=FakePosts()))
    out = await run(registry, "get_analytics")
    assert out["total_impressions"] is None and "Nothing is estimated" in out["note"]


async def test_get_analytics_uses_the_28_day_window_and_the_injected_clock():
    from lumi_ai.tools.data import build

    posts = FakePosts([make_post(1, days_ago=2), make_post(2, days_ago=90)])
    frozen = {s.name: s for s in build(posts, clock_now=lambda: NOW)}["get_analytics"]
    result = await frozen.handler(CTX)
    assert result["posts_in_window"] == 1 and result["profile_id"] == 1


# --- account ------------------------------------------------------------------------


class Profiles:
    async def get_profile(self, profile_id):
        return ProfileInfo(profile_id, "Ana", "ana", "linkedin", ("linkedin",))

    async def get_niche(self, profile_id):
        from lumi_ai.ports import NicheOut

        return NicheOut(
            profile_id, "ai:global", "AI", (), {"x": ("Peer_One",)}, "user", NOW
        )

    async def save_niche(self, profile_id, niche):
        raise NotImplementedError


async def test_connect_account_defaults_to_the_primary_platform_and_returns_the_link():
    links = FakeLinks(
        ConnectLink(already_connected=False, url="https://auth/x", handle=None)
    )
    registry = build_registry(ToolDeps(links=links, profiles=Profiles()))
    out = await run(registry, "connect_account")
    assert out == {
        "already_connected": False,
        "platform": "linkedin",
        "connect_url": "https://auth/x",
        "handle": None,
    }
    assert links.calls == [(1, "linkedin", None)]
    out = await run(registry, "connect_account", platform="x", handle="@Ana ")
    assert links.calls[-1] == (1, "x", "Ana")


async def test_connect_account_already_connected_and_bad_platform():
    links = FakeLinks(
        ConnectLink(already_connected=True, handle="ana", message="Already linked.")
    )
    registry = build_registry(ToolDeps(links=links))
    out = await run(registry, "connect_account", platform="x")
    assert out["already_connected"] is True and out["message"] == "Already linked."
    assert "error" in await run(registry, "connect_account", platform="myspace")
    assert "error" in await run(
        registry, "connect_account"
    )  # no profile store, no platform
    assert len(links.calls) == 1


async def test_backfill_reports_provider_errors_honestly():
    from lumi_ai.ports import ProviderUnavailable

    class Sync:
        async def sync_own_posts(self, profile_id, platform=None):
            if platform == "x":
                raise ProviderUnavailable("feed timed out", provider="pfm")
            return {"stored": 12, "platform": platform}

    registry = build_registry(ToolDeps(post_sync=Sync()))
    assert (await run(registry, "backfill_posts"))["stored"] == 12
    out = await run(registry, "backfill_posts", platform="x")
    assert out == {"error": "could not fetch posts: feed timed out", "provider": "pfm"}
    assert "error" in await run(registry, "backfill_posts", platform="nope")


# --- requests ------------------------------------------------------------------------


async def test_save_user_request_normalises_flags_peers_and_rejects_junk():
    reqs = FakeRequests()
    registry = build_registry(ToolDeps(requests=reqs, profiles=Profiles()))
    out = await run(
        registry,
        "save_user_request",
        handles=["@Peer_One,", "beacons.ai", "not a handle!", ""],
        request="check them",
    )
    by = {s["handle"]: s for s in out["saved"]}
    assert (
        by["peer_one"]["in_peer_set"] is True
        and by["peer_one"]["peer_source"] == "niche_tracked_handles"
    )
    assert by["beacons.ai"]["in_peer_set"] is False
    assert out["invalid"] == ["not a handle!", ""]
    out2 = await run(registry, "save_user_request", handles=["peer_one"])
    assert out2["saved"][0]["already_requested"] is True
    assert all(r[0] == 1 for r in reqs.rows)
    assert reqs.platforms == [
        None,
        None,
        None,
    ]  # no platform given: the service picks it
    await run(registry, "save_user_request", handles=["lead"], platform="linkedin")
    assert reqs.platforms[-1] == "linkedin"
    with pytest.raises(ValueError, match="platform must be one of"):
        await run(registry, "save_user_request", handles=["lead"], platform="myspace")


# --- voice -----------------------------------------------------------------------------


async def test_voice_answers_validated_and_profile_not_found():
    voice = FakeVoice()
    registry = build_registry(ToolDeps(voice=voice))
    assert await run(registry, "get_voice_profile") == {"found": False}
    out = await run(
        registry,
        "answer_style_questions",
        answers=[
            {"question_key": "tone", "answer": " dry "},
            {"question_key": "", "answer": "x"},
        ],
    )
    assert out["recorded"] == 1 and voice.answers[0].answer == "dry"
    assert "error" in await run(registry, "answer_style_questions", answers=[])


# --- listening / alerts / actions ----------------------------------------------------------


async def test_listening_start_stop_and_interval_floor():
    listening = FakeListening()
    registry = build_registry(ToolDeps(listening=listening))
    assert await run(registry, "start_listening", interval_minutes=0) == {
        "profile_id": 1,
        "listening": True,
        "interval_minutes": 1,
    }
    assert listening.config.enabled
    assert (await run(registry, "start_listening"))["interval_minutes"] == 5
    assert await run(registry, "stop_listening") == {
        "profile_id": 1,
        "listening": False,
    }
    assert not listening.config.enabled


async def test_dismiss_alert_by_post_id():
    listening = FakeListening(
        [AlertOut(10, 1, 55, "spike", NOW), AlertOut(11, 2, 66, "spike", NOW)]
    )
    registry = build_registry(ToolDeps(listening=listening))
    assert await run(registry, "dismiss_alert", post_id=55) == {
        "post_id": 55,
        "dismissed": True,
    }
    assert "error" in await run(
        registry, "dismiss_alert", post_id=55
    )  # already dismissed
    assert "error" in await run(
        registry, "dismiss_alert", post_id=66
    )  # another profile's alert
    assert listening.dismissed == [10]


async def test_submit_action_validation_and_ownership():
    rep = FakeRepurpose({7})
    registry = build_registry(ToolDeps(repurpose=rep))
    assert await run(registry, "submit_action", attempt_id=7, action="accept") == {
        "attempt_id": 7,
        "action": "accept",
    }
    assert (
        "edited_text"
        in (await run(registry, "submit_action", attempt_id=7, action="edit"))["error"]
    )
    assert "error" in await run(
        registry, "submit_action", attempt_id=8, action="reject"
    )
    assert "error" in await run(
        registry, "submit_action", attempt_id=7, action="publish"
    )
    assert rep.actions == [(1, 7, "accept", None)]


async def test_submit_action_is_a_write_tool_and_needs_a_real_reason():
    registry = build_registry(ToolDeps(repurpose=FakeRepurpose()))
    with pytest.raises(ValueError, match="not a reason"):
        await registry.call(
            CTX,
            "submit_action",
            {"reason": "submit action", "attempt_id": 7, "action": "accept"},
        )
