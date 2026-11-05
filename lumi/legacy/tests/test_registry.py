import pytest

from app.tools import registry

TEST_TOOL_NAME = "test_echo_tool_for_registry_tests"


@pytest.fixture
def registered_echo_tool():
    @registry.tool(
        name=TEST_TOOL_NAME,
        description="Echoes its input back.",
        parameters={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
    )
    async def echo(value: int) -> dict:
        return {"value": value}

    yield echo
    registry._REGISTRY.pop(TEST_TOOL_NAME, None)


def test_tool_decorator_registers_spec(registered_echo_tool):
    spec = registry.get_tool(TEST_TOOL_NAME)
    assert spec is not None
    assert spec.name == TEST_TOOL_NAME
    assert spec.description == "Echoes its input back."
    assert spec.parameters["required"] == ["value"]


def test_list_tool_specs_shape(registered_echo_tool):
    matches = [s for s in registry.list_tool_specs() if s["function"]["name"] == TEST_TOOL_NAME]
    assert len(matches) == 1

    spec = matches[0]
    assert spec["type"] == "function"
    assert spec["function"]["description"] == "Echoes its input back."
    # reason is injected into the EMITTED spec only (L13 item 4) — the stored
    # spec's required list stays clean (asserted in test_tool_decorator_registers_spec)
    assert spec["function"]["parameters"]["required"] == ["value", "reason"]
    assert "reason" in spec["function"]["parameters"]["properties"]


async def test_call_tool_dispatches_arguments(registered_echo_tool):
    result = await registry.call_tool(TEST_TOOL_NAME, {"value": 42, "reason": "echo test"})
    assert result == {"value": 42}


async def test_call_tool_raises_on_unknown_name():
    with pytest.raises(ValueError, match="unknown tool"):
        await registry.call_tool("definitely_not_a_real_tool", {})
