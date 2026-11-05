"""Account tools: connect a social account (mint an OAuth link) and backfill its posts."""

from __future__ import annotations

from typing import Any, get_args

from lumi_ai.ports import (
    ConnectionLinks,
    OwnPostSync,
    Platform,
    ProfileStore,
    SocialDataError,
)
from lumi_ai.tools.registry import ToolContext, ToolSpec

_PLATFORMS = list(get_args(Platform))


def build_connect(links: ConnectionLinks, profiles: ProfileStore | None) -> ToolSpec:
    async def connect_account(
        ctx: ToolContext, platform: str = "", handle: str = ""
    ) -> dict[str, Any]:
        target = platform or None
        if target is None and profiles is not None:
            info = await profiles.get_profile(ctx.profile_id)
            target = info.primary_platform if info else None
        if target not in _PLATFORMS:
            return {"error": f"platform must be one of: {', '.join(_PLATFORMS)}"}
        clean = (handle or "").lstrip("@").strip() or None
        link = await links.start_connect(ctx.profile_id, target, clean)  # type: ignore[arg-type]
        if link.already_connected:
            return {
                "already_connected": True,
                "platform": target,
                "handle": link.handle,
                "message": link.message
                or f"The {target} account is already connected.",
            }
        return {
            "already_connected": False,
            "platform": target,
            "connect_url": link.url,
            "handle": link.handle or clean,
        }

    return ToolSpec(
        name="connect_account",
        description=(
            "Generate an authorization link for the user to connect a social account "
            "(x, linkedin, facebook, tiktok or instagram). Do NOT ask the user for their handle "
            "first. Call this tool immediately whenever you need them to connect an account, and "
            "present the returned connect_url as a clear clickable markdown link: "
            "[Connect <platform>](<connect_url>). The user authorizes on the platform and the "
            "account is linked automatically."
        ),
        parameters={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": _PLATFORMS,
                    "description": "Platform to connect. Omit to use the profile's primary platform.",
                },
                "handle": {
                    "type": "string",
                    "description": "Optional handle if known. If unknown, leave blank; do not ask for it.",
                },
            },
        },
        handler=connect_account,
        cost="write",
        side_effects="none",  # only mints a URL; the write happens in the OAuth callback
    )


def build_backfill(sync: OwnPostSync) -> ToolSpec:
    async def backfill_posts(ctx: ToolContext, platform: str = "") -> dict[str, Any]:
        target = platform or None
        if target is not None and target not in _PLATFORMS:
            return {"error": f"platform must be one of: {', '.join(_PLATFORMS)}"}
        try:
            return await sync.sync_own_posts(ctx.profile_id, target)  # type: ignore[arg-type]
        except SocialDataError as exc:
            return {"error": f"could not fetch posts: {exc}", "provider": exc.provider}

    return ToolSpec(
        name="backfill_posts",
        description=(
            "Fetch the profile's post history and metrics from its connected account and store "
            "them locally. Run this after connecting an account, or to refresh metrics."
        ),
        parameters={
            "type": "object",
            "properties": {
                "profile_id": {"type": "integer"},
                "platform": {"type": "string", "enum": _PLATFORMS},
            },
            "required": ["profile_id"],
        },
        handler=backfill_posts,
        cost="credits",
        side_effects="writes_db",
        cache_ttl=0,
    )
