import httpx

from lumi_ai.config import AIConfig
from lumi_ai.keys import build_probes
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolContext
from lumi_ai.video.fake import FakeVideoAnalyzer, InMemoryVideoStore
from lumi_ai.video.tools import build

CTX = ToolContext(profile_id=1, config=AIConfig())
URL = "https://cdn.example.com/v.mp4"


async def _call(registry, **args):
    return await registry.call(
        CTX, "analyze_video", {"reason": "the user pasted a video link", **args}
    )


def test_no_tool_is_offered_while_video_is_off() -> None:
    assert build(None, None, AIConfig()) == []


async def test_the_tool_reads_a_pasted_link_then_serves_it_from_the_cache() -> None:
    analyzer, store = FakeVideoAnalyzer(), InMemoryVideoStore()
    registry = build_registry(ToolDeps(), extra=build(analyzer, store, AIConfig()))
    first = await _call(registry, url=URL)
    second = await _call(registry, url=URL)
    assert first["format"] == "talking_head" and first["from_cache"] is False
    assert second["from_cache"] is True and len(analyzer.calls) == 1


async def test_the_tool_says_why_when_it_fails_and_rejects_non_links() -> None:
    analyzer = FakeVideoAnalyzer(
        failing={URL: "the video is over the 20 MB limit (VIDEO_MAX_MB)"}
    )
    registry = build_registry(ToolDeps(), extra=build(analyzer, None, AIConfig()))
    assert "VIDEO_MAX_MB" in (await _call(registry, url=URL))["error"]
    assert "http" in (await _call(registry, url="not a link"))["error"]
    assert len(analyzer.calls) == 1


def _probe(config, handler):
    probes = {
        p.name: p for p in build_probes(config, transport=httpx.MockTransport(handler))
    }
    return probes["video"]


async def test_probe_checks_the_model_without_analysing_anything() -> None:
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"name": "models/gemini-3.5-flash-lite"})

    result = await _probe(
        AIConfig(video_provider="gemini", video_api_key="SECRETKEY"), handler
    ).run()
    assert result.status == "ok" and "SECRETKEY" not in result.detail
    assert [r.method for r in seen] == ["GET"] and seen[0].url.path.endswith(
        "/models/gemini-3.5-flash-lite"
    )


async def test_probe_reports_a_missing_model_and_a_rejected_key_without_the_key() -> (
    None
):
    config = AIConfig(video_provider="gemini", video_api_key="SECRETKEY")
    missing = await _probe(config, lambda r: httpx.Response(404, text="nope")).run()
    assert missing.status == "error" and "VIDEO_MODEL" in missing.detail
    rejected = await _probe(
        config, lambda r: httpx.Response(403, text="bad key SECRETKEY")
    ).run()
    assert (
        rejected.status == "error"
        and "403" in rejected.detail
        and "SECRETKEY" not in rejected.detail
    )
