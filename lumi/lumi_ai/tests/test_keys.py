import httpx

from lumi_ai.config import AIConfig
from lumi_ai.keys import build_probes
from lumi_ai.ports import KeyProbe

KEY = "gsk_super_secret_value"


def _probe(cfg, handler, name="groq", **kw):
    probes = {
        p.name: p
        for p in build_probes(cfg, transport=httpx.MockTransport(handler), **kw)
    }
    return probes[name]


def _models_ok(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models"):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "openai/gpt-oss-120b"},
                    {"id": "openai/gpt-oss-20b"},
                    {"id": "qwen/qwen3.8-27b"},
                    {"id": "whisper-large-v3-turbo"},
                ]
            },
        )
    return httpx.Response(200, json={"choices": []})


def test_all_probes_satisfy_the_port():
    assert all(isinstance(p, KeyProbe) for p in build_probes(AIConfig()))


async def test_missing_required_key_is_an_error_and_optional_is_skipped():
    probes = {p.name: p for p in build_probes(AIConfig())}
    groq = await probes["groq"].run()
    assert groq.status == "error" and "GROQ_API_KEY" in groq.detail
    for name in ("openrouter", "openlux", "jev", "neatlogs", "video"):
        result = await probes[name].run()
        assert result.status == "skipped", name
    assert probes["groq"].required and not probes["openrouter"].required


async def test_groq_ok_with_every_model_present():
    result = await _probe(AIConfig(groq_api_key=KEY), _models_ok).run()
    assert result.status == "ok" and result.warnings == ()


async def test_warns_about_a_configured_model_that_does_not_exist():
    cfg = AIConfig(groq_api_key=KEY, groq_model_fallback="qwen/qwen9-gone")
    result = await _probe(cfg, _models_ok).run()
    assert result.status == "ok"
    assert any("qwen9-gone" in w for w in result.warnings)


async def test_provider_error_is_reported_exactly_and_without_the_key():
    def handler(request):
        return httpx.Response(401, text=f'{{"error": "Invalid API Key {KEY}"}}')

    result = await _probe(AIConfig(groq_api_key=KEY), handler).run()
    assert (
        result.status == "error"
        and "401" in result.detail
        and "Invalid API Key" in result.detail
    )
    assert KEY not in result.detail


async def test_402_on_the_completion_is_an_error_with_the_provider_message():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(402, text="Insufficient credits")

    result = await _probe(AIConfig(groq_api_key=KEY), handler).run()
    assert (
        result.status == "error"
        and "402" in result.detail
        and "Insufficient credits" in result.detail
    )


async def test_network_failure_never_raises():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach host using {KEY}")

    result = await _probe(AIConfig(groq_api_key=KEY), handler).run()
    assert result.status == "error" and KEY not in result.detail


async def test_ping_can_be_turned_off_to_avoid_a_completion():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return _models_ok(request)

    await _probe(AIConfig(groq_api_key=KEY), handler, ping_completion=False).run()
    assert not any(p.endswith("chat/completions") for p in seen)


async def test_openrouter_checks_the_key_before_listing_models():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/auth/key"):
            return httpx.Response(401, text="No auth credentials found")
        return _models_ok(request)

    result = await _probe(
        AIConfig(openrouter_api_key=KEY), handler, name="openrouter"
    ).run()
    assert result.status == "error" and "401" in result.detail
    assert not any(p.endswith("/models") for p in seen)


async def test_video_configured_without_key_is_an_error():
    result = await _probe(
        AIConfig(video_provider="gemini"), _models_ok, name="video"
    ).run()
    assert result.status == "error" and "VIDEO_API_KEY" in result.detail
