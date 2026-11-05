import pytest

from lumi_ai.generation.platforms import (
    PLATFORMS,
    RULES,
    UnknownPlatform,
    measure,
    rules_for,
)


def test_every_platform_has_rules_and_a_cited_source() -> None:
    assert set(RULES) == set(PLATFORMS)
    for rules in RULES.values():
        assert rules.limit_source.strip() and rules.guidance.strip()
        assert rules.target_min <= rules.target_max <= rules.hard_limit


@pytest.mark.parametrize(
    ("platform", "limit"),
    [("x", 280), ("linkedin", 3000), ("instagram", 2200), ("tiktok", 2200)],
)
def test_official_limits(platform: str, limit: int) -> None:
    rules = rules_for(platform)
    assert rules.hard_limit == limit and rules.limit_is_official


def test_facebook_limit_is_defined_and_honest_about_not_being_official() -> None:
    rules = rules_for("facebook")
    assert rules.hard_limit == 63_206
    assert not rules.limit_is_official
    assert "Not published by Meta" in rules.limit_source
    assert rules.target_max < 1000  # what matters is the fold, not the ceiling


def test_instagram_caps_hashtags_at_five_and_only_it_enforces() -> None:
    assert rules_for("instagram").hashtags_max == 5
    assert [p for p, r in RULES.items() if r.hashtag_cap_enforced] == ["instagram"]


def test_unknown_platform_is_an_error_not_x() -> None:
    with pytest.raises(UnknownPlatform, match="myspace"):
        rules_for("myspace")
    assert rules_for(" LinkedIn ").platform == "linkedin"


def test_tiktok_counts_utf16_units() -> None:
    assert measure("tiktok", "hi 😄") == 5  # the emoji is two units
    assert measure("x", "hi 😄") == 4
