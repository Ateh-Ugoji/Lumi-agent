"""Service handling inbound iMessage turns through Lumi AI agent runtime."""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync

from apps.connections.imessage.client import send_imessage
from apps.core import agent_runtime as runtime
from apps.profiles.models import SocialProfile

logger = logging.getLogger(__name__)


def handle_inbound_imessage(
    sender: str,
    text: str,
    profile_id: int | None = None,
    bluebubbles_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Processes an inbound message from iMessage, executes an agent turn, and replies."""
    clean_text = text.strip()
    if not clean_text:
        return {"ok": False, "error": "Empty message"}

    # Resolve target profile
    target_profile: SocialProfile | None = None
    if profile_id:
        target_profile = SocialProfile.objects.filter(pk=profile_id).first()

    if not target_profile:
        # Default to first active social profile
        target_profile = SocialProfile.objects.order_by("-is_primary", "-id").first()

    if not target_profile:
        logger.warning("No SocialProfile available to process iMessage from %s", sender)
        send_imessage(
            recipient=sender,
            message="Lumi: Please connect your account first in the Lumi dashboard.",
            bluebubbles_config=bluebubbles_config,
        )
        return {"ok": False, "error": "No profile configured"}

    # Run agent reasoning turn
    logger.info("Running Lumi agent turn for iMessage from %s (profile %s)", sender, target_profile.pk)
    try:
        result = async_to_sync(runtime.get_runtime().run_turn)(
            target_profile.pk,
            clean_text,
        )
        assistant_reply = result.content or "Lumi processed your request."
    except Exception as exc:
        logger.exception("Error executing agent turn from iMessage: %s", exc)
        assistant_reply = f"Lumi encountered an issue processing your request: {exc}"

    # Send response back to the sender via iMessage
    dispatch_result = send_imessage(
        recipient=sender,
        message=assistant_reply,
        bluebubbles_config=bluebubbles_config,
    )

    return {
        "ok": dispatch_result.success,
        "reply": assistant_reply,
        "sender": sender,
        "profile_id": target_profile.pk,
        "channel": dispatch_result.channel,
        "error": dispatch_result.error,
    }
