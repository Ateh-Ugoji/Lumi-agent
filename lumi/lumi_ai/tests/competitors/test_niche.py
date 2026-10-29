import pytest

from lumi_ai.competitors.niche import make_niche_key, parse_niche_key, slugify


def test_slugify_is_ascii_and_stable() -> None:
    assert slugify("AI tools for creators!") == "ai-tools-for-creators"
    assert slugify("Café  fintech — Lagos") == "cafe-fintech-lagos"
    assert slugify("!!!") == ""


def test_niche_key_round_trips() -> None:
    key = make_niche_key("AI Tools", "NG")
    assert key == "ai-tools:ng"
    assert parse_niche_key(key) == ("ai-tools", "ng")


@pytest.mark.parametrize("scope", [None, "", "global", "Nigeria", "usa"])
def test_unknown_scope_means_global(scope) -> None:
    assert make_niche_key("ai", scope) == "ai:global"


def test_a_niche_without_letters_is_refused() -> None:
    with pytest.raises(ValueError):
        make_niche_key("???")


@pytest.mark.parametrize("raw", ["", "ai", ":ng", "AI Tools:ng", "ai:nigeria"])
def test_malformed_keys_are_refused(raw) -> None:
    with pytest.raises(ValueError):
        parse_niche_key(raw)
