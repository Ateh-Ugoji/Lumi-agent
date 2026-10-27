import base64
import json

import httpx
import pytest

from lumi_ai.config import AIConfig
from lumi_ai.ports import VideoUnavailable
from lumi_ai.video.factory import build_video_analyzer, video_status
from lumi_ai.video.gemini import GeminiVideoAnalyzer

KEY = "AIza-super-secret-key"
URL = "https://cdn.example.com/v.mp4"


async def _public(host):
    return ["93.184.216.34"]


def _config(**kw):
    return AIConfig(video_provider="gemini", video_api_key=KEY, **kw)


def _rig(config, handler):
    seen: list[httpx.Request] = []

    def record(request):
        seen.append(request)
        return handler(request)

    def download(request):
        return httpx.Response(
            200, content=b"VIDEOBYTES", headers={"content-type": "video/mp4"}
        )

    analyzer = GeminiVideoAnalyzer(
        config,
        transport=httpx.MockTransport(record),
        download_transport=httpx.MockTransport(download),
        resolver=_public,
    )
    return analyzer, seen


async def test_analyze_sends_the_video_inline_with_the_key_in_a_header(
    gemini_ok,
) -> None:
    analyzer, seen = _rig(_config(), lambda r: httpx.Response(200, json=gemini_ok))
    result = await analyzer.analyze(URL, context="my caption")
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert request.headers["x-goog-api-key"] == KEY and KEY not in str(request.url)
    body = json.loads(request.content)
    parts = body["contents"][0]["parts"]
    assert base64.b64decode(parts[0]["inline_data"]["data"]) == b"VIDEOBYTES"
    assert parts[0]["inline_data"]["mime_type"] == "video/mp4"
    assert "my caption" in parts[1]["text"], "the prompt goes after the video"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert result.format == "talking_head" and result.cut_count == 14
    assert result.on_screen_text[0] == "10k IN A WEEK" and result.provider == "gemini"
    assert "thinking" not in (result.transcript or "")


async def test_the_model_comes_from_the_config(gemini_ok) -> None:
    analyzer, seen = _rig(
        _config(video_model="gemini-x"), lambda r: httpx.Response(200, json=gemini_ok)
    )
    await analyzer.analyze(URL)
    assert seen[0].url.path.endswith("/models/gemini-x:generateContent")


async def test_youtube_links_go_to_gemini_without_a_download(gemini_ok) -> None:
    analyzer, seen = _rig(_config(), lambda r: httpx.Response(200, json=gemini_ok))
    await analyzer.analyze("https://youtu.be/abc123")
    part = json.loads(seen[0].content)["contents"][0]["parts"][0]
    assert part == {"file_data": {"file_uri": "https://youtu.be/abc123"}}


@pytest.mark.parametrize("status", [400, 401, 429, 500])
async def test_http_errors_say_the_status_and_never_leak_the_key(status) -> None:
    analyzer, _ = _rig(
        _config(), lambda r: httpx.Response(status, text=f"bad key {KEY}")
    )
    with pytest.raises(VideoUnavailable) as err:
        await analyzer.analyze(URL)
    assert str(status) in str(err.value) and KEY not in str(err.value)


async def test_a_blocked_video_is_reported_with_the_reason(gemini_blocked) -> None:
    analyzer, _ = _rig(_config(), lambda r: httpx.Response(200, json=gemini_blocked))
    with pytest.raises(VideoUnavailable, match="PROHIBITED_CONTENT"):
        await analyzer.analyze(URL)


async def test_an_empty_or_non_json_reply_is_unavailable_not_invented() -> None:
    for payload in (
        {"candidates": []},
        {"candidates": [{"content": {"parts": [{"text": "sorry"}]}}]},
    ):
        analyzer, _ = _rig(_config(), lambda r, p=payload: httpx.Response(200, json=p))
        with pytest.raises(VideoUnavailable):
            await analyzer.analyze(URL)


async def test_a_video_over_the_size_limit_never_reaches_the_provider() -> None:
    config = _config(video_max_mb=0)
    analyzer, seen = _rig(config, lambda r: httpx.Response(200, json={}))
    with pytest.raises(VideoUnavailable, match="VIDEO_MAX_MB"):
        await analyzer.analyze(URL)
    assert not seen


def test_factory_is_off_without_a_provider_and_says_why() -> None:
    assert build_video_analyzer(AIConfig()) is None
    assert not video_status(AIConfig()).enabled
    assert "VIDEO_API_KEY" in video_status(AIConfig(video_provider="gemini")).reason
    assert (
        "not supported"
        in video_status(AIConfig(video_provider="nope", video_api_key="k")).reason
    )
    assert (
        build_video_analyzer(AIConfig(video_provider="nope", video_api_key="k")) is None
    )


def test_factory_builds_gemini_when_configured() -> None:
    analyzer = build_video_analyzer(_config())
    assert (
        isinstance(analyzer, GeminiVideoAnalyzer)
        and analyzer.model == "gemini-3.5-flash-lite"
    )


def test_env_names_reach_the_config() -> None:
    config = AIConfig.from_env(
        {
            "VIDEO_PROVIDER": "gemini",
            "VIDEO_API_KEY": "k",
            "VIDEO_MODEL": "gemini-9",
            "VIDEO_MAX_MB": "15",
            "VIDEO_MAX_PER_RUN": "2",
        }
    )
    assert (config.video_provider, config.video_model) == ("gemini", "gemini-9")
    assert (config.video_max_mb, config.video_max_per_run) == (15, 2)
