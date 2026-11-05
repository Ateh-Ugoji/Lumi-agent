"""Claim gate and coverage gate (ported from legacy test_agent_claim_gate / test_coverage_gate)."""

from lumi_ai.agent import gates

CLAIM = (
    "Alright, I've finished digging through @beaconsai's neighbourhood here. "
    "I ran a fresh recon and the results are in."
)
PROMISE = "Got it. I'll do a fresh peer recon focused on @beaconsai and report back."
# --- action-claim gate ------------------------------------------------------


def test_claim_patterns_match_the_reported_transcript():
    assert gates.claims_action_without_tools(CLAIM, tools_ran=False)
    assert gates.claims_action_without_tools(PROMISE, tools_ran=False)
    assert gates.claims_action_without_tools(
        "Running a fresh scan now.", tools_ran=False
    )
    # the 2026-10-20 23:02 live reply: zero tools, presented fabricated data
    assert gates.claims_action_without_tools(
        "Good, fresh numbers now. Here's what's working right now for @beaconsai.",
        tools_ran=False,
    )
    # not claims: neutral replies
    assert not gates.claims_action_without_tools(
        "Hey! What's on your mind?", tools_ran=False
    )
    assert not gates.claims_action_without_tools(
        "I can't look up accounts by URL.", tools_ran=False
    )
    # claims when tools actually ran this turn are fine
    assert not gates.claims_action_without_tools(CLAIM, tools_ran=True)


def test_user_search_command_gates_even_with_novel_reply_wording():
    search_cmd = "Search @beaconsai for me and tell me what's working right now"
    # novel wording the reply-patterns alone would miss
    assert gates.should_nudge(search_cmd, "Here's the overview.", tools_ran=False)
    assert gates.should_nudge(search_cmd, "Good, fresh numbers now.", tools_ran=False)
    # an honest decline passes untouched (no nudge, no disclaimer)
    assert not gates.should_nudge(
        search_cmd,
        "I can't search that right now — no Xpoz credits left.",
        tools_ran=False,
    )
    assert not gates.should_nudge(
        search_cmd, "The scan failed and I have no results to show.", tools_ran=False
    )
    # tools actually ran → no gate
    assert not gates.should_nudge(search_cmd, "Here's what's working.", tools_ran=True)
    # no action requested, no claim → no gate
    assert not gates.should_nudge(
        "hey mahn", "Hey! What's on your mind?", tools_ran=False
    )
    # non-retrieval asks that a text answer legitimately satisfies
    assert not gates.should_nudge(
        "Can you analyze account from me sharing the link?",
        "I can't look up accounts by URL, but I can pull data for specific profiles.",
        tools_ran=False,
    )


def test_bare_handle_tag_is_a_lookup_request():
    # The 2026-10-21 composer @-menu: user tags an account and sends as-is.
    # Prompt rule 13 treats it as save-then-search, so a zero-tool reply with
    # fresh-data presentation must gate; an honest decline must not.
    assert gates.should_nudge("@beaconsai", "Here's the overview.", tools_ran=False)
    assert gates.should_nudge(
        "@beaconsai,", "Sure — running that now.", tools_ran=False
    )
    assert gates.should_nudge("@beaconsai & @wabi", "Looking into it.", tools_ran=False)
    assert not gates.should_nudge(
        "@beaconsai",
        "I can't run a search right now — no Xpoz credits left.",
        tools_ran=False,
    )
    # asking for clarification instead of acting on an unambiguous bare tag
    # gets nudged (rule 13: the tag IS the lookup request)
    assert gates.should_nudge(
        "@beaconsai", "Saved. What should I search for?", tools_ran=False
    )
    # not a bare-tag message (extra words) and not a lookup ask by regex
    assert not gates.should_nudge("thanks @beaconsai", "Anytime!", tools_ran=False)


def test_presenting_phrase_gates_but_stored_data_label_passes():
    # presenting fresh data with zero tools = fabrication by construction
    assert gates.should_nudge(
        "anything", "Here's what's working right now for @beaconsai:", tools_ran=False
    )
    # prompt rule 15's compliant framing: content explicitly labeled as
    # stored/standing data passes (no nudge, no disclaimer)
    assert not gates.should_nudge(
        "Search @beaconsai for me",
        "Here's what's working from my stored recon on @beaconsai: milestone "
        "threads and build-in-public updates.",
        tools_ran=False,
    )
    assert not gates.should_nudge(
        "anything",
        "Based on my standing picture of this niche, the winning pattern is ...",
        tools_ran=False,
    )


def test_decline_wording_does_not_shield_an_embedded_claim():
    # The 2026-10-20 23:13 live reply: honest-sounding framing wrapping a
    # fabricated "I saved them" claim — tools=0, so "went through" was a lie.
    sandwich = (
        "Mahn, keeping it real with you. I can't cleanly finish that request this turn. "
        "Here's where I actually stand: I had saved @beaconsai and @wabi as your user "
        "request, so that part went through. I did not successfully run the scan."
    )
    assert gates.should_nudge(
        "Save @beaconsai and run the search", sandwich, tools_ran=False
    )
    # plain past-tense claims also fire
    assert gates.should_nudge(
        "anything", "I saved those handles already.", tools_ran=False
    )
    assert gates.should_nudge(
        "anything", "Logged it — the request went through.", tools_ran=False
    )
    # but a pure decline with no claim still passes
    assert not gates.should_nudge(
        "Save @beaconsai and run the search",
        "I can't save or search anything right now.",
        tools_ran=False,
    )
    # claims with tools actually run stay untouched
    assert not gates.should_nudge("Save @beaconsai", sandwich, tools_ran=True)


# --- MCP doc-flow gate (connector tools, 2026-10-21) -------------------------


def test_doc_creation_claims_and_requests_are_gated():
    # "make a doc" is an action request: a zero-tool reply fabricates by
    # construction (writes go through a confirmation round-trip, so a past-tense
    # creation claim without tools is impossible honestly)
    assert gates.should_nudge(
        "make a doc about my week", "Sure, working on that.", tools_ran=False
    )
    assert gates.should_nudge(
        "Create a new Google Doc titled Launch", "On it.", tools_ran=False
    )
    assert gates.should_nudge(
        "list my drive files", "Here are your files:", tools_ran=False
    )
    # past-tense creation claim with zero tools
    assert gates.should_nudge(
        "anything", "I created the doc for you just now.", tools_ran=False
    )
    assert gates.should_nudge("anything", "I've drafted the document.", tools_ran=False)
    # "I made a mistake" is NOT a creation claim (needs a doc-ish object)
    assert not gates.should_nudge(
        "what should I say?", "I made a mistake there, sorry.", tools_ran=False
    )
    # the honest decline passes: Google is not connected yet
    assert not gates.should_nudge(
        "make a doc about my week",
        "Google isn't connected yet, so I can't create Docs. Connect it first and I'll do it.",
        tools_ran=False,
    )
    # non-doc requests stay untouched
    assert not gates.should_nudge(
        "what should I tweet?", "Try a build-in-public update.", tools_ran=False
    )


# --- helpers ----------------------------------------------------------------


def test_named_handles_and_trigger_normalization():
    msg = "Search @BeconsAI and @wabi for me"
    assert gates.extract_named_handles(msg) == ["beconsai", "wabi"]
    # de-dup + no @ + no email local-parts
    assert gates.extract_named_handles("mail me at foo@bar.com then @wabi") == ["wabi"]
    # trigger = named handle AND (scan verb OR deliverable OR peer discovery)
    assert gates.coverage_required("Search @beaconsai for me")
    assert gates.coverage_required("make a content plan for @wabi")
    assert gates.coverage_required("find the peers of @beaconsai")
    assert not gates.coverage_required("make a content plan for next week")  # no handle
    assert not gates.coverage_required("hello @wabi")  # handle but no ask
    assert not gates.coverage_required("hi there")


def test_record_scan_coverage_statuses():
    cov = {"a": "not_run", "b": "not_run", "c": "not_run"}
    gates.record_scan_coverage(
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
    gates.record_scan_coverage(
        cov2,
        {"handles": ["x"]},
        {"error": "Xpoz lookups failed for all 1 requested handle(s)"},
    )
    assert cov2["x"].startswith("failed (")
    # handles the USER did not name are never tracked
    cov3 = {"keep": "not_run"}
    gates.record_scan_coverage(
        cov3, {"handles": ["stranger"]}, {"scanned_handles": {"stranger": 5}}
    )
    assert cov3 == {"keep": "not_run"}


def test_coverage_block_labels_stored_frameworks_from_another_niche():
    block = gates.coverage_block(
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
    overlap = gates.coverage_block(
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
    assert "frameworks used: none this turn" in gates.coverage_block(
        {"wabi": "not_run"}, False, None
    )
