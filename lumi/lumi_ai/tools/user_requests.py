"""``save_user_request``: handles the USER asked to look up, kept apart from the peer set."""

from __future__ import annotations

import re
from typing import Any

from lumi_ai.ports import ProfileStore, ReportStore, RequestStore
from lumi_ai.tools.registry import ToolContext, ToolSpec

# 1-30 chars of letters, digits, underscore or dot covers X, Instagram, TikTok and LinkedIn slugs.
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,30}$")


def normalize_handle(raw: object) -> str:
    """'@Beaconsai,' -> 'beaconsai'. Empty string when it cannot be a handle."""
    text = str(raw or "").strip().strip(".,:;!?)]}").lstrip("@").strip().lower()
    return text if _HANDLE_RE.match(text) else ""


async def peer_membership(
    profile_id: int, profiles: ProfileStore | None, reports: ReportStore | None
) -> dict[str, str]:
    """Handle (lowercase) -> the peer source it already belongs to."""
    membership: dict[str, str] = {}
    if profiles is not None:
        niche = await profiles.get_niche(profile_id)
        if niche is not None:
            for handles in niche.tracked_handles.values():
                for raw in handles:
                    if h := normalize_handle(raw):
                        membership.setdefault(h, "niche_tracked_handles")
    if reports is not None:
        for fw in await reports.list_frameworks(profile_id, limit=100):
            for raw in fw.payload.get("top_peer_handles") or []:
                if h := normalize_handle(raw):
                    membership.setdefault(h, "peer_frameworks")
    return membership


def build(
    requests: RequestStore, profiles: ProfileStore | None, reports: ReportStore | None
) -> ToolSpec:
    async def save_user_request(
        ctx: ToolContext, handles: list[str], request: str = ""
    ) -> dict[str, Any]:
        membership = await peer_membership(ctx.profile_id, profiles, reports)
        note = (request or "").strip() or None
        saved: list[dict[str, Any]] = []
        invalid: list[str] = []
        for raw in handles or []:
            handle = normalize_handle(raw)
            if not handle:
                invalid.append(str(raw))
                continue
            row = await requests.save_user_request(ctx.profile_id, handle, note)
            saved.append(
                {
                    "handle": handle,
                    "already_requested": row.already_requested,
                    "in_peer_set": handle in membership,
                    "peer_source": membership.get(handle),
                }
            )
        return {
            "profile_id": ctx.profile_id,
            "saved": saved,
            "invalid": invalid,
            "note": note,
            "guidance": (
                "These are USER-REQUESTED handles, not part of the profile's peer set. "
                "Search them with check_niche_trends. Do NOT run "
                "discover_and_extract_niche_frameworks for them (that writes the peer store). "
                "If in_peer_set is true, tell the user that handle is already in their peer set."
            ),
        }

    return ToolSpec(
        name="save_user_request",
        description=(
            "Record handles/usernames the USER explicitly asked to look up, saving them as "
            "USER REQUESTS (a separate store — never part of the profile's peer set). Costs 0 "
            "credits and performs no search. Returns, per handle: whether it was requested "
            "before and whether it is already in your peer set. Call this BEFORE searching "
            "pasted handles, then use check_niche_trends to actually search them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "integer",
                    "description": "The current profile_id from CURRENT PROFILE CONTEXT.",
                },
                "handles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Handles the user asked to look up (with or without @).",
                },
                "request": {
                    "type": "string",
                    "description": "What the user wants done with these handles, in their words.",
                },
            },
            "required": ["profile_id", "handles"],
        },
        handler=save_user_request,
        side_effects="writes_db",
        cache_ttl=0,
    )
