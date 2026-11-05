"""What a scan teaches the shared handle directory, and the pictures it can reuse.

Every function is a no-op without a ``HandleBook`` and swallows its failures: the directory is a
help layered on the scan, so a table that is down never fails (or changes the answer of) a scan.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence

from lumi_ai.ports import HandleBook, KnownHandle, Platform, PostIn

log = logging.getLogger(__name__)

ORIGIN = "niche"


def authors_of(
    posts: Iterable[PostIn],
    fallback: str = "",
    into: dict[str, KnownHandle] | None = None,
) -> dict[str, KnownHandle]:
    """One entry per author (case-insensitive), keeping the first picture a response carried."""
    out = into if into is not None else {}
    for post in posts:
        name = (post.author_handle or fallback).lstrip("@")
        key = name.lower()
        if not key:
            continue
        photo = post.author_avatar_url or ""
        have = out.get(key)
        if have is None or (not have.avatar_url and photo):
            out[key] = KnownHandle(name, photo)
    return out


async def remember_scanned(
    book: HandleBook | None, platform: Platform, handles: Sequence[str]
) -> None:
    if book is None or not handles:
        return
    try:
        await book.remember_scanned(platform, handles, origin=ORIGIN)
    except Exception as exc:  # noqa: BLE001 - a scan never fails over the directory
        log.warning("handle book: scanned save skipped (%s)", type(exc).__name__)


async def remember_authors(
    book: HandleBook | None, platform: Platform, authors: Mapping[str, KnownHandle]
) -> None:
    if book is None or not authors:
        return
    try:
        await book.remember(platform, list(authors.values()), origin=ORIGIN)
    except Exception as exc:  # noqa: BLE001
        log.warning("handle book: authors save skipped (%s)", type(exc).__name__)


async def known_pictures(
    book: HandleBook | None, platform: Platform, handles: Sequence[str]
) -> Mapping[str, str]:
    """``{lowercase handle: avatar_url}`` for stored accounts; ``{}`` when there is none."""
    if book is None or not handles:
        return {}
    try:
        return await book.pictures(platform, handles)
    except Exception as exc:  # noqa: BLE001
        log.debug("handle book: lookup skipped (%s)", type(exc).__name__)
        return {}
