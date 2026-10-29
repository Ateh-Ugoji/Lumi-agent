from __future__ import annotations

from datetime import UTC, datetime

from lumi_ai.agent.prompts import build_fast_prompt, build_system_prompt
from lumi_ai.ports import ProfileInfo

PROFILE = ProfileInfo(3, "Ana", "ana", "linkedin", ("linkedin", "x"), "America/Lima")
TODAY = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def test_system_prompt_has_the_profile_context_and_todays_date():
    text = build_system_prompt(PROFILE, today=TODAY, niche_title="AI founders")
    assert "- profile_id: 3" in text
    assert "- connected platforms: linkedin, x" in text
    assert "- niche: AI founders" in text
    assert "- timezone: America/Lima" in text
    assert "today's date: Tuesday, 27 October 2026" in text


def test_no_user_or_platform_is_hardcoded():
    text = build_system_prompt(PROFILE, today=TODAY)
    for leaked in ("AtehOfficial", "beaconsai", "sama", "levelsio", "(Twitter)"):
        assert leaked not in text
    assert "connect_account(platform)" in text
    assert "LinkedIn" in text


def test_anti_fabrication_and_evidence_rules_survive_the_port():
    text = build_system_prompt(PROFILE, today=TODAY)
    for needle in (
        "NEVER invent, guess, or fabricate a URL",
        "example.com",
        "Never guess an id",
        "Coverage first",
        "No invented specifics",
        "Free-first ambiguity",
        "TOOLS USED note",
        "never write it as zero",
    ):
        assert needle in text


def test_memory_and_voice_blocks_appear_only_when_given():
    bare = build_system_prompt(PROFILE, today=TODAY)
    assert "AGENT MEMORY (rolling" not in bare and "VOICE SUMMARY (how" not in bare
    full = build_system_prompt(
        PROFILE, today=TODAY, memory_summary="Likes data.", voice_summary="Dry humour."
    )
    assert "Likes data." in full and "Dry humour." in full


def test_fast_prompt_drops_the_rules_but_keeps_persona_and_date():
    fast = build_fast_prompt(PROFILE, today=TODAY)
    assert "Operating rules" not in fast
    assert "Voice and tone" in fast
    assert "27 October 2026" in fast
