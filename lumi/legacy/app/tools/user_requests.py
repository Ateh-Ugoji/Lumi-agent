"""User-requested handle lookups, stored SEPARATELY from the profile's peer set.

When the user pastes or names handles they want looked up (@beaconsai, @wabi, ...),
the agent records them here first (`save_user_request`), then searches them with
`check_niche_trends`. These rows are a user-request log — they never write to
`peer_frameworks` or `listening_matches`, so a requested handle can never silently
become "one of my peers". Recording is free (0 Xpoz credits); searching is a
separate, credit-burning step the agent does explicitly.

Membership reporting: each handle is checked against the profile's current peer
sources (niche defaults, stored framework peer handles, listening authors) so the
agent can say "already in your peer set" instead of re-introducing it as new.
"""

import logging
import re

from sqlmodel import select

from app.agent.prompts import DEFAULT_NICHE_HANDLES
from app.database import session_scope
from app.models.frameworks import PeerFramework
from app.models.listening import ListeningMatch
from app.models.user_request import UserSearchRequest
from app.tools.registry import tool

log = logging.getLogger(__name__)

# X usernames: 1-15 chars, letters/digits/underscore only.
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def _normalize_handle(raw: object) -> str:
    """'@Beaconsai,' -> 'beaconsai'. Returns '' when it cannot be a valid handle."""
    text = str(raw or "").strip().strip(".,:;!?)]}").lstrip("@").strip().lower()
    return text if _HANDLE_RE.match(text) else ""


async def _peer_membership(profile_id: int) -> dict[str, str]:
    """Map of handle (lowercase) -> which peer source it came from."""
    membership: dict[str, str] = {}
    for handle in DEFAULT_NICHE_HANDLES:
        membership[handle.lower()] = "niche_default"
    try:
        async with session_scope() as session:
            frameworks = (
                await session.exec(
                    select(PeerFramework).where(PeerFramework.profile_id == profile_id)
                )
            ).all()
            for row in frameworks:
                for raw in ((row.payload or {}).get("top_peer_handles") or []):
                    normalized = _normalize_handle(raw)
                    if normalized:
                        membership.setdefault(normalized, "peer_frameworks")
            authors = (
                await session.exec(
                    select(ListeningMatch.author_handle)
                    .where(ListeningMatch.profile_id == profile_id)
                    .distinct()
                )
            ).all()
            for raw in authors:
                normalized = _normalize_handle(raw)
                if normalized:
                    membership.setdefault(normalized, "listening_matches")
    except Exception as exc:  # noqa: BLE001 — membership is best-effort reporting
        log.warning("peer-set membership lookup failed for profile %s: %s", profile_id, exc)
    return membership


@tool(
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
    side_effects="writes_db",
)
async def save_user_request(profile_id: int, handles: list[str], request: str = "") -> dict:
    membership = await _peer_membership(profile_id)
    saved: list[dict] = []
    invalid: list[str] = []
    note = (request or "").strip() or None

    async with session_scope() as session:
        for raw in handles or []:
            normalized = _normalize_handle(raw)
            if not normalized:
                invalid.append(str(raw))
                continue
            prior = (
                await session.exec(
                    select(UserSearchRequest).where(
                        UserSearchRequest.profile_id == profile_id,
                        UserSearchRequest.handle == normalized,
                    )
                )
            ).first()
            session.add(
                UserSearchRequest(profile_id=profile_id, handle=normalized, request_note=note)
            )
            saved.append(
                {
                    "handle": normalized,
                    "already_requested": prior is not None,
                    "in_peer_set": normalized in membership,
                    "peer_source": membership.get(normalized),
                }
            )
        await session.commit()

    if invalid:
        log.info("save_user_request: rejected invalid handles %s", invalid)

    return {
        "profile_id": profile_id,
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
