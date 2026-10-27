import openai

from app.services import enforcement
from app.services.enforcement import check_length, check_must_keep, enforce


def test_check_length_rejects_over_limit():
    result = check_length("x" * 281, limit=280)
    assert result.passed is False
    assert "281" in result.feedback


def test_check_length_accepts_at_or_under_limit():
    assert check_length("x" * 280, limit=280).passed is True


def test_check_must_keep_flags_missing_phrases():
    result = check_must_keep("some caption", must_keep_phrases=["https://example.com"])
    assert result.passed is False
    assert "https://example.com" in result.feedback


def test_check_must_keep_passes_when_all_present():
    assert check_must_keep("check https://example.com now", ["https://example.com"]).passed is True


async def test_enforce_skips_judge_when_must_keep_fails(monkeypatch):
    called = False

    async def fake_judge(original, rewrite):
        nonlocal called
        called = True
        return "yes", 0.9, "jev"

    monkeypatch.setattr(enforcement, "judge_caption", fake_judge)

    result = await enforce("original", "rewrite missing the link", must_keep_phrases=["https://example.com"])

    assert result.must_keep_passed is False
    assert result.judge_verdict is None
    assert result.judge_confidence is None
    assert called is False


async def test_enforce_calls_judge_when_checks_pass(monkeypatch):
    calls = []

    async def fake_judge(original, rewrite):
        calls.append((original, rewrite))
        return "yes", 0.9, "jev"

    monkeypatch.setattr(enforcement, "judge_caption", fake_judge)

    result = await enforce("original text", "rewrite text", must_keep_phrases=[])

    assert result.must_keep_passed is True
    assert result.judge_verdict == "yes"
    assert result.judge_confidence == 0.9
    assert result.judge_source == "jev"
    assert calls == [("original text", "rewrite text")]


async def test_enforce_degrades_when_all_judges_fail(monkeypatch):
    async def failing_judge(original, rewrite):
        raise openai.APIError(message="all judges down", request=None, body=None)

    monkeypatch.setattr(enforcement, "judge_caption", failing_judge)

    result = await enforce("original text", "rewrite text", must_keep_phrases=[])

    assert result.must_keep_passed is True
    assert result.judge_verdict is None
    assert result.judge_source == "none"
    assert "flagged for manual review" in result.feedback
