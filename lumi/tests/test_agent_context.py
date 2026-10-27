import pytest

from app.agent.prompts import SYSTEM_PROMPT, build_system_prompt
from app.tools import registry

PROFILE_TOOL_NAME = "test_profile_context_tool_for_tests"


@pytest.fixture
def registered_profile_tool():
    @registry.tool(
        name=PROFILE_TOOL_NAME,
        description="Accepts an optional profile_id.",
        parameters={
            "type": "object",
            "properties": {"profile_id": {"type": "integer"}},
        },
    )
    async def profile_tool(profile_id: int | None = None) -> dict:
        return {"profile_id": profile_id}

    yield profile_tool
    registry._REGISTRY.pop(PROFILE_TOOL_NAME, None)
    registry.set_current_profile_id(None)


def test_build_system_prompt_includes_profile_context():
    prompt = build_system_prompt(2, "AtehOfficial", "Ateh Ugoji")
    assert "profile_id: 2" in prompt
    assert "handle: @AtehOfficial" in prompt
    assert "name: Ateh Ugoji" in prompt
    assert prompt.startswith(SYSTEM_PROMPT)


def test_system_prompt_has_anti_fabrication_rules():
    assert "NEVER invent, guess, or fabricate a URL" in SYSTEM_PROMPT
    assert "example.com" in SYSTEM_PROMPT
    assert "CURRENT PROFILE CONTEXT" in SYSTEM_PROMPT
    assert "Profile N not found" in SYSTEM_PROMPT
    assert "Never guess an id" in SYSTEM_PROMPT


async def test_call_tool_injects_missing_profile_id(registered_profile_tool):
    registry.set_current_profile_id(2)
    result = await registry.call_tool(PROFILE_TOOL_NAME, {"reason": "profile context check"})
    assert result == {"profile_id": 2}


async def test_call_tool_injects_none_profile_id(registered_profile_tool):
    registry.set_current_profile_id(7)
    result = await registry.call_tool(PROFILE_TOOL_NAME, {"profile_id": None, "reason": "profile context check"})
    assert result == {"profile_id": 7}


async def test_call_tool_preserves_explicit_profile_id(registered_profile_tool):
    registry.set_current_profile_id(2)
    result = await registry.call_tool(PROFILE_TOOL_NAME, {"profile_id": 5, "reason": "profile context check"})
    assert result == {"profile_id": 5}


async def test_call_tool_without_profile_context_stays_none(registered_profile_tool):
    registry.set_current_profile_id(None)
    result = await registry.call_tool(PROFILE_TOOL_NAME, {"reason": "profile context check"})
    assert result == {"profile_id": None}


async def test_call_tool_does_not_touch_tools_without_profile_id():
    @registry.tool(
        name="test_no_profile_tool_for_tests",
        description="No profile_id property.",
        parameters={"type": "object", "properties": {"value": {"type": "integer"}}},
    )
    async def no_profile_tool(value: int) -> dict:
        return {"value": value}

    try:
        registry.set_current_profile_id(2)
        result = await registry.call_tool(
            "test_no_profile_tool_for_tests", {"value": 3, "reason": "profile context check"}
        )
        assert result == {"value": 3}
    finally:
        registry._REGISTRY.pop("test_no_profile_tool_for_tests", None)
        registry.set_current_profile_id(None)


def test_get_analytics_profile_id_not_required():
    from app.tools.analytics import get_analytics

    spec = registry.get_tool("get_analytics")
    assert spec is not None
    assert "profile_id" not in spec.parameters.get("required", [])
    assert get_analytics is not None
