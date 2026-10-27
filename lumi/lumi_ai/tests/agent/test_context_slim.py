"""Greeting gate and context slimming (ported from legacy tests/test_loop_gates.py)."""

from lumi_ai.agent.context import slim_for_context
from lumi_ai.agent.turn_class import is_greeting_only


def test_greeting_variants_are_greetings():
    for msg in (
        "hi",
        "Hi!",
        "hey there",
        "hello.",
        "what's up?",
        "good morning",
        "thanks a lot",
        "lol",
        "ping",
        "How are you doing?",
    ):
        assert is_greeting_only(msg), msg


def test_tasks_are_not_greetings():
    for msg in (
        "repurpose this for linkedin",
        "show me my analytics",
        "hi how was your day?",
        "check trending posts and alert me",
        "",
        "hi " + "there " * 10,
    ):
        assert not is_greeting_only(msg), msg


def test_slim_drops_series_but_keeps_totals():
    payload = {
        "total_impressions": 100,
        "reach_series": [1, 2, 3],
        "saves_series": [4, 5, 6],
        "allocation": [
            {"label": "Text Posts", "pct": 52.4, "amount": "1x views", "color": "#fff"}
        ],
        "top_posts": [{"caption": "c" * 300, "impressions": 9, "likes": 1}],
        "is_live_data": True,
    }
    slim = slim_for_context("get_analytics", payload)
    assert "reach_series" not in slim and "saves_series" not in slim
    assert slim["total_impressions"] == 100
    assert slim["allocation"] == [
        {"label": "Text Posts", "pct": 52.4, "amount": "1x views"}
    ]
    assert len(slim["top_posts"][0]["caption"]) == 120


def test_slim_leaves_other_tools_and_errors_alone():
    posts = {"posts": [{"caption": "x"}]}
    assert slim_for_context("get_posts", posts) is posts
    err = {"error": "Profile 1 not found"}
    assert slim_for_context("get_analytics", err) is err
