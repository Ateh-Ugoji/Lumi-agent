from __future__ import annotations

from apps.connections.handles.ranking import (
    clean_followers,
    context_words,
    mix,
    normalize_query,
    parse_platforms,
    query_key,
    rank,
)

from .fakes import row


def test_normalize_strips_the_at_and_whitespace() -> None:
    assert normalize_query("  @@Naval ") == "Naval"
    assert query_key(" @NAVAL") == "naval"
    assert normalize_query(None) == ""  # type: ignore[arg-type]


def test_platforms_are_validated_deduped_and_default_to_x() -> None:
    assert parse_platforms("x, Instagram,x,bogus") == ["x", "instagram"]
    assert parse_platforms("") == ["x"] and parse_platforms(None) == ["x"]
    assert parse_platforms(["TikTok", "reddit"]) == ["tiktok", "reddit"]
    assert parse_platforms("bogus") == ["x"]


def test_context_keeps_three_words() -> None:
    assert context_words("Thanks to my friend the one and only") == [
        "thanks",
        "to",
        "my",
    ]
    assert context_words("") == []


def test_followers_are_never_coerced_to_zero() -> None:
    assert clean_followers(5) == 5 and clean_followers(0) == 0
    for bad in (None, -1, "5", True, 1.5):
        assert clean_followers(bad) is None


def test_rank_order_exact_then_saved_then_context_then_followers() -> None:
    rows = [
        row("zed", followers=10),
        row("naval", followers=1),
        row("alpha", followers=None),
        row("beta", followers=500),
        row("dbuser", followers=None, source="db"),
        row("gamma", name="Naval fan", followers=2),
    ]
    out = rank(rows, "naval", db_keys={"x:dbuser"}, ctx_words=[])
    assert [r.handle for r in out] == [
        "naval",
        "dbuser",
        "beta",
        "zed",
        "gamma",
        "alpha",
    ]
    with_ctx = rank(rows, "zzz", db_keys=set(), ctx_words=["naval"])
    assert with_ctx[0].handle in {"naval", "gamma"}


def test_mix_is_half_saved_half_live() -> None:
    saved = [row(f"s{i}", source="cache") for i in range(8)]
    live = [row(f"l{i}") for i in range(8)]
    out = mix(saved + live, "zz", db_keys=set())
    assert len(out) == 10
    assert [r.source for r in out].count("live") == 5


def test_mix_hands_leftover_slots_to_the_other_side() -> None:
    saved = [row("s0", source="cache")]
    live = [row(f"l{i}") for i in range(12)]
    out = mix(saved + live, "zz", db_keys=set())
    assert len(out) == 10 and sum(r.source == "live" for r in out) == 9
    only_saved = mix(
        [row(f"s{i}", source="cache") for i in range(12)], "zz", db_keys=set()
    )
    assert len(only_saved) == 10


def test_exact_match_goes_first_and_profile_handles_count_as_saved() -> None:
    rows = [row("a1", source="cache"), row("naval"), row("dbn", source="db")]
    out = mix(rows, "naval", db_keys={"x:dbn"})
    assert out[0].handle == "naval" and len(out) == 3
    live_as_db = mix([row("p1"), row("l1")], "zz", db_keys={"x:p1"})
    assert len(live_as_db) == 2
