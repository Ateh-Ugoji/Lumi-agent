from unittest.mock import AsyncMock, patch

from app.services.voice import (
    _format_prior_profile,
    _heuristic_voice_extraction,
    extract_voice_from_captions,
)


def test_heuristic_voice_extraction_structure():
    captions = [
        "Building in public is hard. But shipping daily changes everything.",
        "Stop overthinking your stack. Just deploy it.",
        "What is the biggest blocker in your agent loop?",
        "3 tips for cleaner code:\n- Keep functions small\n- Don't nest conditions\n- Test early",
        "Never wait for perfection. Real feedback comes after launch.",
    ]

    result = _heuristic_voice_extraction(captions)

    assert "archetype_name" in result
    assert "creator_bio_summary" in result
    assert "perspective" in result

    assert result["posts_analyzed_count"] == 5
    assert "tone" in result
    assert "emoji_use" in result
    assert "hook_style" in result
    assert "vocabulary" in result
    assert "structure" in result
    assert "call_to_action_style" in result
    assert "target_length_words" in result
    assert "things_they_never_do" in result
    assert "representative_excerpts" in result
    assert len(result["representative_excerpts"]) > 0



def test_format_prior_profile_renders_fields():
    prior = {"tone": "punchy", "emoji_use": "none", "hook_style": "contrarian", "structure": "one-liners"}
    block = _format_prior_profile(prior, version=3)
    assert "Version: 3" in block
    assert "tone: punchy" in block
    assert "emoji_use: none" in block
    assert "hook_style: contrarian" in block
    # empty values are skipped
    assert "call_to_action_style" not in block


def test_heuristic_voice_extraction_empty():
    result = _heuristic_voice_extraction([])
    assert result["tone"] == "neutral, direct"
    assert result["emoji_use"] == "minimal"


async def test_extract_voice_from_captions_falls_back_when_no_keys():
    captions = ["Post 1", "Post 2", "Post 3", "Post 4", "Post 5"]
    result = await extract_voice_from_captions(captions)

    assert isinstance(result, dict)
    assert "tone" in result
    assert "vocabulary" in result


async def test_extract_voice_from_captions_with_llm(monkeypatch):
    captions = ["Post 1", "Post 2", "Post 3", "Post 4", "Post 5"]

    mock_llm_json = """
    {
        "tone": "sharp, direct, sarcastic",
        "emoji_use": "none, plain text only",
        "hook_style": "short contrarian statement",
        "vocabulary": "developer jargon, concise syntax",
        "structure": "single line punches",
        "things_they_never_do": "never uses inspirational hashtags",
        "representative_excerpts": ["Post 1", "Post 2"]
    }
    """

    class FakeChoice:
        def __init__(self):
            class FakeMessage:
                content = mock_llm_json
            self.message = FakeMessage()

    class FakeCompletion:
        def __init__(self):
            self.choices = [FakeChoice()]

    with patch("app.services.voice.get_settings") as mock_settings:
        mock_settings.return_value.groq_api_key = "fake_key"
        mock_settings.return_value.openrouter_api_key = ""

        with patch("app.services.voice.chat_completion_with_fallback", new=AsyncMock(return_value=FakeCompletion())):
            result = await extract_voice_from_captions(captions)

            assert result["tone"] == "sharp, direct, sarcastic"
            assert result["hook_style"] == "short contrarian statement"
            assert result["things_they_never_do"] == "never uses inspirational hashtags"
