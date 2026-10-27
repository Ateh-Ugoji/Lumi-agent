"""Which media URLs are worth sending to a video provider.

Video analysis costs money per minute, so the rule is strict: a URL goes through only when the
source says it is a video (``kind == "video"``), when it clearly *looks* like one (``kind`` is
``None``, as with X's ``mediaUrls``), or when the user pasted it. Images and GIFs never do, and
an unknown URL that does not look like a video is skipped rather than guessed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from urllib.parse import urlparse

from lumi_ai.ports import MediaRef

VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v")
#: Hosts whose media URLs are video even without a file suffix.
VIDEO_HOSTS = ("video.twimg.com",)
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")


def _parsed(url: str):
    try:
        return urlparse(url.strip())
    except ValueError:
        return None


def is_http_url(url: str) -> bool:
    parts = _parsed(url)
    return bool(parts and parts.scheme in {"http", "https"} and parts.hostname)


def is_youtube(url: str) -> bool:
    parts = _parsed(url)
    return bool(parts and (parts.hostname or "").lower() in YOUTUBE_HOSTS)


def looks_like_video(url: str) -> bool:
    """``True`` only when the URL itself says video: a known suffix, a video host or YouTube."""
    parts = _parsed(url)
    if parts is None or not is_http_url(url):
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.path.lower().endswith(VIDEO_SUFFIXES)
        or host in VIDEO_HOSTS
        or host in YOUTUBE_HOSTS
    )


def video_urls(
    media: Sequence[MediaRef], *, pasted: Iterable[str] = ()
) -> tuple[list[str], list[str]]:
    """``(urls to analyse, skipped URLs)`` in input order, without duplicates.

    ``pasted`` are URLs the user gave explicitly: any http(s) URL counts, because they asked.
    """
    chosen: dict[str, None] = {}
    skipped: dict[str, None] = {}
    for ref in media:
        url = ref.url.strip()
        if not is_http_url(url):
            skipped.setdefault(url)
        elif ref.kind == "video" or (ref.kind is None and looks_like_video(url)):
            chosen.setdefault(url)
        elif ref.kind is None:
            skipped.setdefault(url)  # unknown type and no sign of video: never guess
    for raw in pasted:
        url = raw.strip()
        if is_http_url(url):
            chosen.setdefault(url)
        else:
            skipped.setdefault(url)
    return list(chosen), [u for u in skipped if u not in chosen]
