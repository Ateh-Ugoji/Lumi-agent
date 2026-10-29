import pytest

from lumi_ai.json_utils import JSONExtractionError, extract_json, extract_json_object


def test_plain_json() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_with_language_tag() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_fenced_without_tag_and_prose_around() -> None:
    text = 'Sure, here you go:\n```\n{"a": [1, 2]}\n```\nHope that helps.'
    assert extract_json(text) == {"a": [1, 2]}


def test_backticks_inside_content_survive() -> None:
    # The old strip("`") would have damaged the trailing backtick of the value.
    text = '```json\n{"tip": "use `uv run`"}\n```'
    assert extract_json_object(text) == {"tip": "use `uv run`"}


def test_prose_before_unfenced_json() -> None:
    assert extract_json('Result: {"ok": true} done') == {"ok": True}


def test_braces_inside_strings_do_not_confuse_balance() -> None:
    assert extract_json('x {"s": "a } b { c"} y') == {"s": "a } b { c"}


def test_escaped_quote_inside_string() -> None:
    assert extract_json(r'{"s": "say \"hi\" }"}') == {"s": 'say "hi" }'}


def test_array_value() -> None:
    assert extract_json("here: [1, 2, 3]") == [1, 2, 3]


def test_skips_invalid_candidate_and_finds_next() -> None:
    assert extract_json('{bad json} then {"good": 1}') == {"good": 1}


@pytest.mark.parametrize("text", ["", "   ", "no json here", "{unbalanced"])
def test_failure(text: str) -> None:
    with pytest.raises(JSONExtractionError):
        extract_json(text)


def test_object_required() -> None:
    with pytest.raises(JSONExtractionError):
        extract_json_object("[1, 2]")
