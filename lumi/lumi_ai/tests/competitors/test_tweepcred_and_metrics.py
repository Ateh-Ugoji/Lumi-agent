"""Tests for TweepCred follower ratio health and X algorithm weighted engagement."""

from __future__ import annotations

import pytest

from lumi_ai.competitors.metrics import (
    calculate_tweepcred_ratio_health,
    engagement_total,
    x_algorithm_weighted_engagement,
)
from lumi_ai.competitors.pipeline import PipelineDeps
from lumi_ai.competitors.tools import CompetitorServices, build
from lumi_ai.config import AIConfig
from lumi_ai.ports import ProfileInfo
from lumi_ai.tests.competitors.support import FakeReports, FakeSocial, TaggerLLM
from lumi_ai.tools.registry import ToolContext


class DummyProfiles:
    async def get_profile(self, profile_id: int):
        return ProfileInfo(handle="@test", main_network="x")


def test_engagement_total_vs_x_weighted_engagement():
    # Post with 100 likes and 2 comments
    flat = engagement_total(likes=100, comments=2, shares=5)
    assert flat == 107

    # Post with 100 likes and 2 comments vs post with 10 likes and 20 comments
    post_a_weighted = x_algorithm_weighted_engagement(likes=100, comments=2, shares=5)
    post_b_weighted = x_algorithm_weighted_engagement(likes=10, comments=20, shares=5)

    # In flat engagement: Post A (107) > Post B (35)
    # In X Heavy Ranker: Post B (10*1 + 20*13.5 + 5*1 = 285) >> Post A (100 + 27 + 5 = 132)
    assert post_b_weighted > post_a_weighted


def test_calculate_tweepcred_ratio_health_unpenalized_small_account():
    # Account following < 2500 accounts is unpenalized
    health = calculate_tweepcred_ratio_health(followers_count=500, following_count=1200)
    assert health["is_penalized"] is False
    assert health["division_factor"] == 1.0
    assert health["status"] == "healthy"
    assert health["reach_loss_percentage"] == 0.0


def test_calculate_tweepcred_ratio_health_unpenalized_good_ratio():
    # Account following > 2500 but ratio <= 0.60
    health = calculate_tweepcred_ratio_health(followers_count=10000, following_count=3000)
    assert health["following_to_followers_ratio"] < 0.6
    assert health["is_penalized"] is False
    assert health["status"] == "healthy"


def test_calculate_tweepcred_ratio_health_penalized():
    # Account following > 2500 with ratio > 0.60 (e.g. 3000 following, 1500 followers -> ratio 2.0)
    health = calculate_tweepcred_ratio_health(followers_count=1500, following_count=3000)
    assert health["is_penalized"] is True
    assert health["division_factor"] > 1.0
    assert health["status"] in ("warning", "critical")
    assert health["reach_loss_percentage"] > 0.0
    assert health["unfollow_target_to_fix"] > 0


@pytest.mark.asyncio
async def test_tweepcred_tool_spec_and_execution():
    pipeline = PipelineDeps(
        social=FakeSocial(),
        llm=TaggerLLM(),
        reports=FakeReports(),
        peer_posts=None,
    )
    services = CompetitorServices(
        pipeline=pipeline,
        profiles=DummyProfiles(),
    )
    tools = {t.name: t for t in build(services)}
    assert "audit_x_tweepcred" in tools

    ctx = ToolContext(profile_id=1, config=AIConfig())
    audit_tool = tools["audit_x_tweepcred"]

    # Test direct calculation via tool
    res = await audit_tool.handler(ctx, followers=1000, following=4000)
    assert res["is_penalized"] is True
    assert res["division_factor"] > 1.0
    assert "⚠️ Warning" in res["explanation"]
