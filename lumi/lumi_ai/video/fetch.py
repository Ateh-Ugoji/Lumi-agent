"""Download a video from a URL somebody else supplied, without becoming an open proxy.

The URL comes from scraped posts or from a user, so it is untrusted: only http(s), only public
addresses (a private, loopback or link-local address is refused, including after a redirect),
a hard size cap while streaming, and a video content type. Known limit: the name is resolved
once for the check and again by the HTTP client, so a hostile DNS that changes its answer
between the two could still slip through; run the worker without access to internal networks.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from lumi_ai.ports import VideoUnavailable
from lumi_ai.video.urls import is_http_url

MAX_REDIRECTS = 3
_SUFFIX_MIME = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
_GENERIC_TYPES = {"application/octet-stream", "binary/octet-stream", ""}

#: ``resolver(host)`` returns the IP addresses the name points to.
Resolver = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class FetchedVideo:
    data: bytes
    mime_type: str


async def resolve_host(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM
    )
    return sorted({info[4][0] for info in infos})


async def _check_public(url: str, resolver: Resolver) -> None:
    if not is_http_url(url):
        raise VideoUnavailable("the video URL is not http(s)")
    host = urlparse(url).hostname or ""
    try:
        addresses = await resolver(host)
    except OSError:
        raise VideoUnavailable(f"cannot resolve {host}") from None
    if not addresses:
        raise VideoUnavailable(f"cannot resolve {host}")
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw.split("%")[0])
        except ValueError:
            raise VideoUnavailable(f"{host} resolved to a bad address") from None
        if not address.is_global:
            raise VideoUnavailable("the video URL points to a non-public address")


def _mime(content_type: str | None, url: str) -> str:
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind.startswith("video/"):
        return kind
    if kind in _GENERIC_TYPES:
        path = urlparse(url).path.lower()
        for suffix, mime in _SUFFIX_MIME.items():
            if path.endswith(suffix):
                return mime
    raise VideoUnavailable(f"the URL is not a video (content-type {kind or 'missing'})")


async def fetch_video(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = resolve_host,
) -> FetchedVideo:
    """Download ``url`` (at most ``max_bytes``). Raises ``VideoUnavailable`` with a plain reason."""
    current = url.strip()
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport
    ) as http:
        for _ in range(MAX_REDIRECTS + 1):
            await _check_public(current, resolver)
            try:
                async with http.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise VideoUnavailable("redirect without a location")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise VideoUnavailable(
                            f"the video host answered HTTP {response.status_code}"
                        )
                    mime = _mime(response.headers.get("content-type"), current)
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise VideoUnavailable(
                            f"the video is {int(declared) // 1_048_576} MB, over the "
                            f"{max_bytes // 1_048_576} MB limit (VIDEO_MAX_MB)"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise VideoUnavailable(
                                f"the video is over the {max_bytes // 1_048_576} MB limit "
                                "(VIDEO_MAX_MB)"
                            )
                        chunks.append(chunk)
                    return FetchedVideo(b"".join(chunks), mime)
            except httpx.HTTPError as exc:
                raise VideoUnavailable(
                    f"could not download the video: {type(exc).__name__}"
                ) from None
    raise VideoUnavailable("too many redirects")
