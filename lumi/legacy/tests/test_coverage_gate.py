"""Coverage evidence gate + finish_reason handling (PROMPT 4 acceptance).

The Beacons failure (chat_messages row 273): three tools ran, none of them a
scan of the handles the user named, and the reply opened "I have the full
picture" with a plan that never mentioned @beaconsai. This suite pins the fix:

- per-handle coverage (scanned / failed / not_run) computed from this turn's
  check_niche_trends results;
- one corrective nudge when a named handle was never run — even when OTHER
  tools ran ("some tool ran" no longer satisfies the gate);
- a forced coverage block + "full picture" strip while coverage is incomplete;
- get_peer_advice provenance (niche_title / source_handles / age_days) for
  rule 18;
- finish_reason == "length" -> one continuation, then an honest cut-off notice;
- prompt rules 17-20 and today's date in the system prompt.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from app.agent import loop
from app.tools import registry

BEACONS_MSG = (
    "Search through this account Beacons.ai @beaconsai find their peers recon. "
    "Find what is working. People like @wabi and all. And make a content plan for 30 days"
)

# Tools the evidence gate observes by name. Overridden with fakes for the turn
# and restored afterwards (the registry is a process-global import side effect).
FAKE_TOOLS = (
    "check_niche_trends",
    "save_user_request",
    "get_peer_advice",
    "discover_and_extract_niche_frameworks",
)


@pytest.fixture
def fake_recon_tools():
    saved = {name: registry._REGISTRY.get(name) for name in FAKE_TOOLS}
    calls: dict[str, list[dict]] = {name: [] for name in FAKE_TOOLS}
    results: dict[str, dict] = {}

    def _make(name: str):
        async def _tool(**kwargs):
            calls[name].append(kwargs)
            return copy.deepcopy(results.get(name, {"ok": True}))

        return _tool

    permissive = {
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "handles": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "request": {"type": "string"},
            "min_likes": {"type": "integer"},
        },
    }
    for name in FAKE_TOOLS:
        registry._REGISTRY[name] = registry.ToolSpec(
            name=name,
            description="fake tool for coverage-gate tests",
            parameters=permissive,
            func=_make(name),
        )
    yield calls, results
    for name, spec in saved.items():
        if spec is None:
            registry._REGISTRY.pop(name, None)
        else:
            registry._REGISTRY[name] = spec


def _completion(
    content: str | None = None, tool_calls: list | None = None, finish_reason: str | None = None
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
    )


def _tool_call(name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.fixture
def turn_harness(monkeypatch):
    captured: dict = {"saved": [], "model_messages": [], "completions": []}

    async def fake_save(profile_id, role, content, tool_name=None, tool_calls=None, reason=None, tools_used=None):
        captured["saved"].append({"role": role, "content": content, "reason": reason, "tools_used": tools_used})

    async def fake_history(profile_id):
        return []

    async def fake_profile(profile_id):
        return None

    async def fake_completion(messages, tools, effort=None):
        captured["model_messages"].append([dict(m) for m in messages])
        return captured["completions"][len(captured["model_messages"]) - 1]

    async def fake_refresh_tools(force: bool = False):
        return None

    monkeypatch.setattr(loop, "_save_message", fake_save)
    monkeypatch.setattr(loop, "_load_history", fake_history)
    monkeypatch.setattr(loop, "_load_profile", fake_profile)
    monkeypatch.setattr(loop, "build_system_prompt", lambda *a, **k: "system")
    monkeypatch.setattr(loop, "get_profile_summary", lambda *a, **k: "")
    monkeypatch.setattr(loop, "chat_completion_with_fallback", fake_completion)
    monkeypatch.setattr(loop, "_schedule_memory_extraction", lambda *a, **k: None)
    # The classification row is written fire-and-forget into the real DB;
    # keep the turn hermetic (same pattern as memory extraction).
    monkeypatch.setattr(loop, "_schedule_classification", lambda *a, **k: None)
    monkeypatch.setattr(loop.mcp_service, "refresh_tools", fake_refresh_tools)
    return captured


# --- helpers ----------------------------------------------------------------


def test_named_handles_and_trigger_normalization():
    msg = "Search @BeconsAI and @wabi for me"
    assert loop._extract_named_handles(msg) == ["beconsai", "wabi"]
    # de-dup + no @ + no email local-parts
    assert loop._extract_named_handles("mail me at foo@bar.com then @wabi") == ["wabi"]
    # trigger = named handle AND (scan verb OR deliverable OR peer discovery)
    assert loop._coverage_required("Search @beaconsai for me")
    assert loop._coverage_required("make a content plan for @wabi")
    assert loop._coverage_required("find the peers of @beaconsai")
    assert not loop._coverage_required("make a content plan for next week")  # no handle
    assert not loop._coverage_required("hello @wabi")  # handle but no ask
    assert not loop._coverage_required("hi there")


def test_record_scan_coverage_statuses():
    cov = {"a": "not_run", "b": "not_run", "c": "not_run"}
    loop._record_scan_coverage(
        cov,
        {"handles": ["a", "@B", "c"]},
        {
            "scanned_handles": {"a": 10, "b": 10},
            "failed_handles": ["@c: Xpoz 402"],
        },
    )
    assert cov["a"] == "scanned (10 posts)"
    assert cov["b"] == "scanned (10 posts)"
    assert cov["c"] == "failed (Xpoz 402)"
    # a whole-call error fails every requested handle it did not scan
    cov2 = {"x": "not_run"}
    loop._record_scan_coverage(
        cov2, {"handles": ["x"]}, {"error": "Xpoz lookups failed for all 1 requested handle(s)"}
    )
    assert cov2["x"].startswith("failed (")
    # handles the USER did not name are never tracked
    cov3 = {"keep": "not_run"}
    loop._record_scan_coverage(cov3, {"handles": ["stranger"]}, {"scanned_handles": {"stranger": 5}})
    assert cov3 == {"keep": "not_run"}


def test_coverage_block_labels_stored_frameworks_from_another_niche():
    block = loop._coverage_block(
        {"beaconsai": "not_run", "wabi": "not_run"},
        peers_discovered=False,
        frameworks={
            "found": True,
            "niche_title": "AI Startup Founders",
            "source_handles": ["karpathy"],
            "age_days": 6,
        },
    )
    assert block.startswith("Recon coverage:")
    assert "@beaconsai: not_run" in block
    assert "peers discovered: not run" in block
    assert (
        "frameworks used: stored AI Startup Founders set, 6d old, different accounts than named"
        in block
    )
    # when a named handle IS among the sources, the block says so
    overlap = loop._coverage_block(
        {"wabi": "scanned (3 posts)"},
        peers_discovered=True,
        frameworks={
            "found": True,
            "niche_title": "AI",
            "source_handles": ["wabi"],
            "age_days": 0,
        },
    )
    assert "covers the named accounts" in overlap
    # no advice fetched this turn
    assert "frameworks used: none this turn" in loop._coverage_block(
        {"wabi": "not_run"}, False, None
    )


# --- acceptance: the Beacons replay -----------------------------------------


async def test_beacons_scan_failure_opens_with_coverage_block(
    turn_harness, fake_recon_tools
):
    calls, results = fake_recon_tools
    results["save_user_request"] = {
        "profile_id": 2,
        "saved": [{"handle": "beaconsai"}, {"handle": "wabi"}],
        "invalid": [],
    }
    results["check_niche_trends"] = {
        "profile_id": 2,
        "new_matches_found": 3,
        "viral_posts": [{"author": "wabi", "caption": "x", "likes": 77}],
        "scanned_handles": {"beaconsai": 10},
        "failed_handles": ["@wabi: Xpoz 402"],
    }
    turn_harness["completions"] = [
        _completion(
            tool_calls=[
                _tool_call(
                    "save_user_request",
                    json.dumps(
                        {
                            "profile_id": 2,
                            "handles": ["beaconsai", "wabi"],
                            "request": "find their peers recon",
                            "reason": "user asked to recon the tagged handles",
                        }
                    ),
                ),
                _tool_call(
                    "check_niche_trends",
                    json.dumps(
                        {
                            "profile_id": 2,
                            "handles": ["beaconsai", "wabi"],
                            "reason": "scan the tagged handles the user named",
                        }
                    ),
                ),
            ]
        ),
        _completion(content="I have the full picture. Here is your 30-day plan."),
    ]

    result = await loop._run_agent_loop(2, BEACONS_MSG)

    # opens with the coverage block, naming both handles' real status
    assert result.content.startswith("Recon coverage:")
    assert "@beaconsai: scanned (10 posts)" in result.content
    assert "@wabi: failed (Xpoz 402)" in result.content
    assert "peers discovered: not run" in result.content
    # "full picture" is stripped while coverage is incomplete
    assert "full picture" not in result.content.lower()
    assert "partial picture" in result.content
    # both handles were ATTEMPTED (one scanned, one failed) -> no corrective
    # nudge, exactly two completions
    assert len(turn_harness["model_messages"]) == 2
    assert calls["check_niche_trends"] and calls["save_user_request"]


async def test_gate_fires_even_when_an_unrelated_tool_ran(turn_harness, fake_recon_tools):
    calls, _results = fake_recon_tools
    turn_harness["completions"] = [
        _completion(
            tool_calls=[
                _tool_call(
                    "save_user_request",
                    json.dumps(
                        {
                            "profile_id": 2,
                            "handles": ["beaconsai", "wabi"],
                            "reason": "user asked to recon the tagged handles",
                        }
                    ),
                )
            ]
        ),
        _completion(content="Here is your plan for the accounts."),
        # after the coverage nudge the model still does not scan -> block forced
        _completion(content="Here is your plan for the accounts."),
    ]

    result = await loop._run_agent_loop(2, BEACONS_MSG)

    # save_user_request ran, but the named handles never got scanned: the
    # coverage nudge fires anyway (the old gate was satisfied by ANY tool).
    assert calls["save_user_request"]
    assert len(turn_harness["model_messages"]) == 3
    second_call_users = [
        m for m in turn_harness["model_messages"][1] if m.get("role") == "user"
    ]
    assert not any("NOT yet scanned" in str(m.get("content")) for m in second_call_users)
    third_call_users = [
        m for m in turn_harness["model_messages"][2] if m.get("role") == "user"
    ]
    assert any("NOT yet scanned" in str(m.get("content")) for m in third_call_users)
    assert any(
        "check_niche_trends" in str(m.get("content")) for m in third_call_users
    )
    # and the still-unscanned reply is forced open with the coverage block
    assert result.content.startswith("Recon coverage:")
    assert "@beaconsai: not_run" in result.content
    assert "@wabi: not_run" in result.content


async def test_complete_coverage_leaves_reply_untouched(turn_harness, fake_recon_tools):
    _calls, results = fake_recon_tools
    results["check_niche_trends"] = {
        "profile_id": 2,
        "new_matches_found": 0,
        "viral_posts": [],
        "scanned_handles": {"beaconsai": 10, "wabi": 10},
        "failed_handles": [],
    }
    reply = "Scanned both accounts. Here's what's working for them."
    turn_harness["completions"] = [
        _completion(
            tool_calls=[
                _tool_call(
                    "check_niche_trends",
                    json.dumps(
                        {
                            "profile_id": 2,
                            "handles": ["beaconsai", "wabi"],
                            "reason": "scan the tagged handles the user named",
                        }
                    ),
                )
            ]
        ),
        _completion(content=reply),
    ]

    result = await loop._run_agent_loop(2, BEACONS_MSG)

    assert result.content == reply
    assert len(turn_harness["model_messages"]) == 2


async def test_honest_zero_tool_decline_stays_untouched(turn_harness, fake_recon_tools):
    reply = "I can't scan that right now — no Xpoz credits left."
    turn_harness["completions"] = [_completion(content=reply)]

    result = await loop._run_agent_loop(2, BEACONS_MSG)

    assert result.content == reply
    assert len(turn_harness["model_messages"]) == 1


# --- acceptance: provenance for rule 18 -------------------------------------


async def test_get_peer_advice_returns_provenance(monkeypatch):
    from app.tools import advice

    monkeypatch.setattr(
        advice,
        "query_frameworks",
        lambda *a, **k: [
            {
                "id": "2:5",
                "text": "Niche: AI Startup Founders",
                "metadata": {"niche_title": "AI Startup Founders"},
                "distance": 0.1,
            }
        ],
    )
    monkeypatch.setattr(
        advice,
        "query_peer_posts",
        lambda *a, **k: [
            {"id": "p1", "text": "post", "metadata": {"author": "karpathy"}, "distance": 0.2}
        ],
    )

    async def jev_down(*a, **k):
        return None

    monkeypatch.setattr(advice.jev, "ask_noul", jev_down)

    result = await advice.get_peer_advice(profile_id=1, query="launch hooks")

    assert result["source"] == "store"
    assert result["niche_title"] == "AI Startup Founders"
    assert result["source_handles"] == ["karpathy"]
    assert "age_days" in result  # unknown without DB rows -> None, never a fake number


# --- acceptance: finish_reason == length -------------------------------------


async def test_length_finish_reason_continues_once(turn_harness):
    turn_harness["completions"] = [
        _completion(content="If a post takes ", finish_reason="length"),
        _completion(content="two hours, batch it.", finish_reason="stop"),
    ]

    result = await loop._run_agent_loop(1, "write me a long thread about shipping")

    assert result.content == "If a post takes two hours, batch it."
    assert len(turn_harness["model_messages"]) == 2
    continuation_users = [
        m for m in turn_harness["model_messages"][1] if m.get("role") == "user"
    ]
    assert any("cut off mid-sentence" in str(m.get("content")) for m in continuation_users)


async def test_repeated_length_says_where_it_was_cut(turn_harness):
    turn_harness["completions"] = [
        _completion(
            content="Weeks 1-2: ship daily. If a post takes ", finish_reason="length"
        ),
        _completion(content="two hours,", finish_reason="length"),
    ]

    result = await loop._run_agent_loop(1, "write me a long thread about shipping")

    assert 'cut off again' in result.content
    assert result.content.startswith("Weeks 1-2: ship daily.")
    # exactly ONE continuation — the gate must never loop
    assert len(turn_harness["model_messages"]) == 2


# --- acceptance: prompt rules 17-20 + date ----------------------------------


def test_system_prompt_has_rules_17_to_20():
    from app.agent.prompts import SYSTEM_PROMPT

    assert "Coverage first." in SYSTEM_PROMPT
    assert "source_handles" in SYSTEM_PROMPT  # rule 18 reads the provenance field
    assert "placeholder" in SYSTEM_PROMPT  # rule 19: [your number] instead of invention
    assert "state your assumption in the first line" in SYSTEM_PROMPT  # rule 20


def test_system_prompt_injects_todays_date():
    from app.agent.prompts import build_system_prompt

    prompt = build_system_prompt(2, handle="AtehOfficial", name="Ateh", memory_summary="")
    assert "today's date:" in prompt
    assert "(UTC)" in prompt
