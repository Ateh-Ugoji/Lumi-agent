from types import SimpleNamespace

from typesafe_sdk import TypeSafeError

from app.agent.providers import TIER_MODELS
from app.services import repurpose
from app.services.repurpose import (
    classify_difficulty,
    classify_difficulty_by_rule,
    generate_platform_repurpose,
)


def test_short_x_caption_with_nothing_to_protect_is_easy():
    assert classify_difficulty_by_rule("shipping the new build tonight", "x", []) == "easy"


def test_platform_name_is_normalized():
    assert classify_difficulty_by_rule("shipping the new build tonight", " X ", []) == "easy"


def test_cross_platform_rewrite_is_standard():
    assert classify_difficulty_by_rule("shipping the new build tonight", "linkedin", []) == "standard"


def test_one_protected_item_is_standard():
    assert classify_difficulty_by_rule("thanks @neatlogs for the help", "x", []) == "standard"


def test_over_x_limit_is_hard():
    assert classify_difficulty_by_rule("a" * 281, "x", []) == "hard"


def test_long_source_is_not_hard_for_linkedin():
    assert classify_difficulty_by_rule("a" * 281, "linkedin", []) == "standard"


def test_many_protected_items_is_hard():
    text = "launch with @alice and @bob, details at https://lumi.dev"
    assert classify_difficulty_by_rule(text, "x", []) == "hard"


def test_must_keep_phrases_count_toward_hard():
    assert classify_difficulty_by_rule("big day", "x", ["v2.0", "Oct 12", "neatHack"]) == "hard"


async def test_classify_difficulty_uses_jev_when_available(monkeypatch):
    async def fake_jev(source_text, platform, must_keep_phrases):
        return "hard"

    monkeypatch.setattr(repurpose, "_classify_difficulty_jev", fake_jev)

    assert await classify_difficulty("shipping the new build tonight", "x", []) == "hard"


async def test_classify_difficulty_falls_back_to_rule_when_jev_fails(monkeypatch):
    async def failing_jev(source_text, platform, must_keep_phrases):
        raise TypeSafeError("jev down")

    monkeypatch.setattr(repurpose, "_classify_difficulty_jev", failing_jev)

    assert await classify_difficulty("shipping the new build tonight", "x", []) == "easy"


async def test_generate_routes_tier_to_its_model(monkeypatch):
    requested = []

    async def fake_completion(messages, tools, model=None):
        requested.append(model)
        content = '{"platform": "x", "adapted_text": "rewritten", "changes": []}'
        completion = SimpleNamespace(model=model, choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        return completion, "groq"

    monkeypatch.setattr(repurpose, "chat_completion_with_provider", fake_completion)

    result = await generate_platform_repurpose("original", platform="x", tier="small")

    assert requested == [TIER_MODELS["small"]]
    assert result["adapted_text"] == "rewritten"
    assert result["tier"] == "small"
    assert result["model"] == TIER_MODELS["small"]
    assert result["provider"] == "groq"
