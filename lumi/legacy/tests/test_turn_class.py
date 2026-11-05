"""Turn classifier (L13 item 1 / PROMPT 5 item 1): rules first, Jev second.

Rules are pure regex + the greeting whitelist (zero latency). Jev stage 2 is
behind a kill-switch (default OFF), runs ONLY when no rule matched, enforces
its own timeout, and applies the L13 item 8 confidence banding:
>= 0.85 act on any class / 0.6-0.85 act only for free-tier classes /
< 0.6 -> other. A classifier failure can only widen to the full path.
"""

import asyncio

from app.agent import loop as loop_mod
from app.agent import turn_class
from app.agent.turn_class import (
    FREE_TIER_CLASSES,
    allowed_for,
    classify,
    classify_turn,
    is_greeting_only,
    log_hash,
    log_preview,
)


class _Settings:
    """Stand-in for app.config.Settings with only the classifier knobs."""

    def __init__(self, *, enabled: bool = True, timeout_ms: int = 800):
        self.turn_class_jev_enabled = enabled
        self.turn_class_jev_timeout_ms = timeout_ms
        self.turn_class_jev_high = 0.85
        self.turn_class_jev_low = 0.6


def _use_settings(monkeypatch, **kwargs) -> None:
    monkeypatch.setattr(turn_class, "get_settings", lambda: _Settings(**kwargs))


def _use_scores(monkeypatch, scores: dict[str, float] | None) -> None:
    async def fake_ask_noul(state, questions):
        return scores

    monkeypatch.setattr(turn_class.jev, "ask_noul", fake_ask_noul)


# --- rules: the seven classes ------------------------------------------------


def test_greeting_is_chitchat_fast_path():
    for msg in ("hi", "thanks", "ok", "hey there"):
        result = classify(msg)
        assert result.final_class == "chitchat", msg
        assert result.path == "fast", msg
        assert result.rule_matched == "greeting", msg
        assert result.jev_called is False


def test_history_meta_questions():
    for msg in (
        "what tools did you use?",
        "list them",
        "list them out",
        "can you call the tools that was used for this? list them out",
        "what did you just do?",
        "show me the tool history",
    ):
        result = classify(msg)
        assert result.final_class == "history_meta", msg
        assert result.rule_matched is not None, msg
        assert result.ambiguous is False, msg


def test_memory_rules():
    for msg in ("remember that I hate hashtags", "what do you know about me?"):
        result = classify(msg)
        assert result.final_class == "memory", msg
    # "remember to <task>" is an instruction, NOT a memory write
    result = classify("remember to scan @wabi tomorrow")
    assert result.final_class != "memory"
    assert result.final_class == "live_scan"


def test_read_cheap_own_data():
    for msg in (
        "show me my posts",
        "how are my posts doing?",
        "what are my analytics?",
        "how's my voice profile?",
    ):
        result = classify(msg)
        assert result.final_class == "read_cheap", msg


def test_live_scan_rules():
    for msg in (
        "scan @wabi for viral posts",
        "@sama",
        "what's trending today?",
        "check what's trending in ai",
    ):
        result = classify(msg)
        assert result.final_class == "live_scan", msg
        assert result.path == "full", msg


def test_write_rules():
    for msg in (
        "create a doc with my latest numbers",
        "connect my account",
        "submit the suggested edit",
    ):
        result = classify(msg)
        assert result.final_class == "write", msg


def test_ambiguous_rules_land_on_other():
    result = classify("scan @wabi and show me my analytics")
    assert result.ambiguous is True
    assert result.final_class == "other"
    assert result.path == "full"
    # every hit is retained so scripts can find the conflict
    assert "scan_verb" in result.matched_rules
    assert "read_own_data" in result.matched_rules


def test_unmatched_message_is_other_without_jev():
    result = classify("repurpose that caption for linkedin")
    assert result.rule_matched is None
    assert result.final_class == "other"
    assert result.jev_called is False


# --- class -> allowed tools --------------------------------------------------


def test_allowed_tools_per_class():
    assert allowed_for("chitchat").costs == frozenset()
    assert allowed_for("history_meta").costs == frozenset()
    memory = allowed_for("memory")
    assert memory.names == frozenset({"remember", "recall_memory"})
    assert allowed_for("read_cheap").costs == frozenset({"free"})
    assert allowed_for("live_scan").costs == frozenset({"free", "credits", "llm"})
    assert allowed_for("write").costs == frozenset({"free", "write"})
    assert allowed_for("other").costs == frozenset({"free", "credits", "llm", "write"})
    # unknown classes never fail open narrower than the full path
    assert allowed_for("nope").costs == allowed_for("other").costs


def test_free_tier_classes_exclude_paid_paths():
    assert "read_cheap" in FREE_TIER_CLASSES
    assert "history_meta" in FREE_TIER_CLASSES
    assert "live_scan" not in FREE_TIER_CLASSES
    assert "write" not in FREE_TIER_CLASSES


# --- stage 2: Jev behind the kill-switch -------------------------------------


async def test_jev_disabled_by_default_no_call(monkeypatch):
    _use_settings(monkeypatch, enabled=False)

    async def boom(state, questions):
        raise AssertionError("Jev stage must not run when disabled")

    monkeypatch.setattr(turn_class.jev, "ask_noul", boom)
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.jev_called is False
    assert result.final_class == "other"


async def test_rules_match_skips_jev_even_when_enabled(monkeypatch):
    _use_settings(monkeypatch, enabled=True)

    async def boom(state, questions):
        raise AssertionError("Jev stage must not run when a rule matched")

    monkeypatch.setattr(turn_class.jev, "ask_noul", boom)
    result = await classify_turn("what tools did you use?")
    assert result.final_class == "history_meta"
    assert result.jev_called is False


async def test_jev_high_confidence_adopts_any_class(monkeypatch):
    _use_settings(monkeypatch, enabled=True)
    _use_scores(
        monkeypatch,
        {"history_meta": 0.92, "read_cheap": 0.10, "live_scan": 0.05, "write": 0.03},
    )
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.jev_called is True
    assert result.jev_class == "history_meta"
    assert result.jev_confidence == 0.92
    assert result.final_class == "history_meta"
    assert result.jev_error is None
    assert result.jev_latency_ms is not None and result.jev_latency_ms >= 0
    assert result.jev_probs is not None
    assert {p["name"] for p in result.jev_probs} == {
        "history_meta",
        "read_cheap",
        "live_scan",
        "write",
    }


async def test_jev_mid_band_free_class_is_adopted(monkeypatch):
    _use_settings(monkeypatch, enabled=True)
    _use_scores(
        monkeypatch,
        {"read_cheap": 0.70, "live_scan": 0.65, "history_meta": 0.2, "write": 0.1},
    )
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.final_class == "read_cheap"  # free tier: 0.6-0.85 acts


async def test_jev_mid_band_paid_class_routed_to_other(monkeypatch):
    _use_settings(monkeypatch, enabled=True)
    _use_scores(
        monkeypatch,
        {"live_scan": 0.70, "read_cheap": 0.40, "history_meta": 0.2, "write": 0.1},
    )
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.jev_class == "live_scan"
    assert result.jev_confidence == 0.70
    assert result.final_class == "other"  # a middling guess never starts credits


async def test_jev_below_low_is_other(monkeypatch):
    _use_settings(monkeypatch, enabled=True)
    _use_scores(
        monkeypatch,
        {"write": 0.40, "live_scan": 0.35, "read_cheap": 0.2, "history_meta": 0.1},
    )
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.final_class == "other"
    assert result.jev_class == "write"


async def test_jev_unavailable_falls_back_to_other(monkeypatch):
    _use_settings(monkeypatch, enabled=True)
    _use_scores(monkeypatch, None)
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.final_class == "other"
    assert result.jev_error == "unavailable"
    assert result.jev_probs is None
    assert result.jev_confidence is None


async def test_jev_timeout_is_bounded_and_falls_back(monkeypatch):
    _use_settings(monkeypatch, enabled=True, timeout_ms=50)

    async def slow(state, questions):
        await asyncio.sleep(5)
        return {"write": 0.99}

    monkeypatch.setattr(turn_class.jev, "ask_noul", slow)
    result = await classify_turn("repurpose that caption for linkedin")
    assert result.final_class == "other"
    assert result.jev_error == "timeout"
    # the hard cap held (50ms configured, nowhere near the 5s sleep)
    assert result.jev_latency_ms is not None and result.jev_latency_ms < 2000


# --- greeting gate: single source of truth -----------------------------------


def test_greeting_whitelist_reexported_from_loop():
    assert loop_mod.is_greeting_only is is_greeting_only
    assert is_greeting_only("hi")
    assert not is_greeting_only("scan @wabi")


# --- log helpers (L13 item 9 columns) ----------------------------------------


def test_log_preview_collapses_and_truncates():
    assert log_preview("  hi\n   there  ") == "hi there"
    long = "x" * 500
    assert len(log_preview(long)) == 120


def test_log_hash_is_stable_and_normalized():
    assert log_hash("Hello  World") == log_hash("hello world")
    assert log_hash("hello world") != log_hash("hello there")
    assert len(log_hash("hi")) == 32
