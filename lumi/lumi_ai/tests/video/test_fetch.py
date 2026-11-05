import httpx
import pytest

from lumi_ai.ports import VideoUnavailable
from lumi_ai.video.fetch import fetch_video

MB = 1_048_576


def _resolver(mapping):
    async def resolve(host):
        return mapping.get(host, ["93.184.216.34"])

    return resolve


async def _fetch(
    handler, url="https://cdn.example.com/v.mp4", *, max_bytes=MB, resolver=None
):
    return await fetch_video(
        url,
        max_bytes=max_bytes,
        timeout=5,
        transport=httpx.MockTransport(handler),
        resolver=resolver or _resolver({}),
    )


async def test_downloads_a_video_and_reports_its_mime() -> None:
    video = await _fetch(
        lambda r: httpx.Response(
            200, content=b"abc", headers={"content-type": "video/mp4"}
        )
    )
    assert video.data == b"abc" and video.mime_type == "video/mp4"


async def test_octet_stream_is_accepted_only_with_a_video_suffix() -> None:
    def handler(request):
        return httpx.Response(
            200, content=b"x", headers={"content-type": "application/octet-stream"}
        )

    assert (await _fetch(handler)).mime_type == "video/mp4"
    with pytest.raises(VideoUnavailable, match="not a video"):
        await _fetch(handler, "https://cdn.example.com/blob")


async def test_a_web_page_is_not_a_video() -> None:
    with pytest.raises(VideoUnavailable, match="text/html"):
        await _fetch(
            lambda r: httpx.Response(
                200, text="<html>", headers={"content-type": "text/html"}
            )
        )


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "192.168.1.1"]
)
async def test_non_public_addresses_are_refused_before_any_request(address) -> None:
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200)

    with pytest.raises(VideoUnavailable, match="non-public"):
        await _fetch(handler, resolver=_resolver({"cdn.example.com": [address]}))
    assert not called


async def test_a_redirect_to_an_internal_host_is_refused() -> None:
    def handler(request):
        return httpx.Response(302, headers={"location": "http://internal.local/v.mp4"})

    with pytest.raises(VideoUnavailable, match="non-public"):
        await _fetch(handler, resolver=_resolver({"internal.local": ["10.1.2.3"]}))


async def test_a_redirect_to_a_public_host_is_followed() -> None:
    def handler(request):
        if request.url.host == "cdn.example.com":
            return httpx.Response(
                302, headers={"location": "https://other.example.org/v.mp4"}
            )
        return httpx.Response(
            200, content=b"ok", headers={"content-type": "video/webm"}
        )

    assert (await _fetch(handler)).data == b"ok"


async def test_only_http_and_https() -> None:
    with pytest.raises(VideoUnavailable, match="not http"):
        await _fetch(lambda r: httpx.Response(200), "file:///etc/passwd")


async def test_size_cap_by_header_and_while_streaming() -> None:
    big = MB + 1
    with pytest.raises(VideoUnavailable, match="VIDEO_MAX_MB"):
        await _fetch(
            lambda r: httpx.Response(
                200,
                content=b"x",
                headers={"content-type": "video/mp4", "content-length": str(big)},
            )
        )
    with pytest.raises(VideoUnavailable, match="VIDEO_MAX_MB"):
        await _fetch(
            lambda r: httpx.Response(
                200, content=b"x" * big, headers={"content-type": "video/mp4"}
            )
        )


async def test_http_errors_and_redirect_loops_say_why() -> None:
    with pytest.raises(VideoUnavailable, match="HTTP 403"):
        await _fetch(lambda r: httpx.Response(403))
    with pytest.raises(VideoUnavailable, match="too many redirects"):
        await _fetch(
            lambda r: httpx.Response(
                302, headers={"location": "https://cdn.example.com/v.mp4"}
            )
        )
