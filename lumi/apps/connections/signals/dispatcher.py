"""Signal event dispatcher for post velocity spikes and competitor breakouts.

Dispatches actionable creator alerts over iMessage, WhatsApp, or outbound webhooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.connections.imessage.client import send_imessage

logger = logging.getLogger(__name__)


@dataclass
class SignalEvent:
    event_type: str  # "spike.velocity" | "author.golden_hour" | "competitor.breakout" | "tweepcred.degraded"
    title: str
    message: str
    data: dict[str, Any]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def format_signal_message(signal: SignalEvent) -> str:
    """Formats an algorithmic signal event into a crisp creator alert."""
    if signal.event_type == "spike.velocity":
        post_url = signal.data.get("url", "")
        velocity = signal.data.get("velocity", "3.5x")
        replies = signal.data.get("replies", 0)
        return (
            f"⚡ LUMI SPIKE ALERT: Your post is pacing at {velocity} average engagement!\n"
            f"Replies: {replies} (13.5x algorithm weight).\n"
            f"Jump in to keep conversation momentum going!\n{post_url}"
        )

    if signal.event_type == "author.golden_hour":
        return (
            "⏳ LUMI GOLDEN HOUR SPRINT: You have unreplied comments in the first 60 minutes!\n"
            "Author responses trigger the algorithm's +75.0x engagement multiplier. "
            "Reply to top comments right now to maximize feed reach."
        )

    if signal.event_type == "competitor.breakout":
        handle = signal.data.get("handle", "peer")
        hook = signal.data.get("hook", "")
        lift = signal.data.get("lift", "3.2x")
        return (
            f"🎯 COMPETITOR BREAKOUT: @{handle} just published a post pacing with {lift} lift!\n"
            f"Winning Hook Formula: \"{hook}\"\n"
            f"Open Lumi to draft an original spin in your voice."
        )

    if signal.event_type == "tweepcred.degraded":
        ratio = signal.data.get("ratio", "0.65")
        factor = signal.data.get("division_factor", "2.1x")
        return (
            f"⚠️ TWEEPCRED REACH WARNING: Your follow-to-follower ratio is {ratio}.\n"
            f"Twitter algorithm is applying a {factor} reach division penalty.\n"
            "Unfollow non-reciprocal accounts to restore full PageRank distribution."
        )

    return f"📢 LUMI SIGNAL ({signal.title}):\n{signal.message}"


def dispatch_signal_alert(
    signal: SignalEvent,
    imessage_recipient: str | None = None,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    """Dispatches a signal alert to configured creator channels."""
    formatted_text = format_signal_message(signal)
    results: dict[str, Any] = {"signal": signal.event_type, "dispatched_channels": []}

    # Dispatch to iMessage if recipient configured
    if imessage_recipient:
        res = send_imessage(recipient=imessage_recipient, message=formatted_text)
        results["imessage"] = {
            "success": res.success,
            "recipient": res.recipient,
            "error": res.error,
        }
        if res.success:
            results["dispatched_channels"].append("imessage")

    # Dispatch to external webhook if configured
    if webhook_url:
        import httpx
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    webhook_url,
                    json={
                        "event": signal.event_type,
                        "title": signal.title,
                        "text": formatted_text,
                        "data": signal.data,
                        "timestamp": signal.timestamp,
                    },
                )
                results["webhook"] = {"status_code": resp.status_code, "ok": resp.is_success}
                if resp.is_success:
                    results["dispatched_channels"].append("webhook")
        except Exception as exc:
            results["webhook"] = {"error": str(exc), "ok": False}

    return results
