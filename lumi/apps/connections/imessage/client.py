"""macOS Native AppleScript and BlueBubbles iMessage client for Lumi.

Sends iMessage alerts and messages either via local macOS ``osascript``
or via remote BlueBubbles REST API gateway.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class IMessageResult:
    success: bool
    channel: str  # "native_macos" | "bluebubbles"
    recipient: str
    message: str
    error: str | None = None


def is_macos_native_available() -> bool:
    """True if running on macOS where osascript and Messages.app are available."""
    return platform.system() == "Darwin"


def send_native_applescript(recipient: str, message: str) -> IMessageResult:
    """Send an iMessage via macOS AppleScript through native Messages.app."""
    if not is_macos_native_available():
        return IMessageResult(
            success=False,
            channel="native_macos",
            recipient=recipient,
            message=message,
            error="Native AppleScript iMessage is only supported on macOS.",
        )

    clean_recipient = recipient.strip()
    # Escape quotes and backslashes for AppleScript string literals
    clean_message = message.replace("\\", "\\\\").replace('"', '\\"')

    # AppleScript targeting Messages.app
    # Uses 'participant' or 'buddy' of the iMessage service
    applescript = f'''
    tell application "Messages"
        try
            set targetBuddy to participant "{clean_recipient}" of chat 1
            send "{clean_message}" to targetBuddy
            return "ok"
        on error
            try
                -- fallback by creating/targeting the service
                set targetService to 1st service whose service type = iMessage
                set targetBuddy to buddy "{clean_recipient}" of targetService
                send "{clean_message}" to targetBuddy
                return "ok"
            on error errMsg
                -- fallback: try sending directly to chat with recipient
                set targetChat to chat id "any;-;{clean_recipient}"
                send "{clean_message}" to targetChat
                return "ok"
            end try
        end try
    end tell
    '''

    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            logger.info("iMessage successfully dispatched to %s via native macOS", clean_recipient)
            return IMessageResult(
                success=True,
                channel="native_macos",
                recipient=clean_recipient,
                message=message,
            )
        err = proc.stderr.strip() or f"AppleScript exited with code {proc.returncode}"
        logger.warning("Failed to send iMessage via AppleScript: %s", err)
        return IMessageResult(
            success=False,
            channel="native_macos",
            recipient=clean_recipient,
            message=message,
            error=err,
        )
    except Exception as exc:
        logger.exception("Error executing osascript iMessage send: %s", exc)
        return IMessageResult(
            success=False,
            channel="native_macos",
            recipient=clean_recipient,
            message=message,
            error=str(exc),
        )


async def send_bluebubbles(
    base_url: str,
    password: str,
    recipient: str,
    message: str,
) -> IMessageResult:
    """Send an iMessage via BlueBubbles server REST API."""
    url = f"{base_url.rstrip('/')}/api/v1/message/text"
    payload = {
        "chatGuid": f"iMessage;-;{recipient.strip()}",
        "text": message,
        "method": "private-api",
    }
    params = {"password": password}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, params=params)
            if resp.status_code in (200, 201):
                return IMessageResult(
                    success=True,
                    channel="bluebubbles",
                    recipient=recipient,
                    message=message,
                )
            return IMessageResult(
                success=False,
                channel="bluebubbles",
                recipient=recipient,
                message=message,
                error=f"BlueBubbles HTTP {resp.status_code}: {resp.text}",
            )
    except Exception as exc:
        return IMessageResult(
            success=False,
            channel="bluebubbles",
            recipient=recipient,
            message=message,
            error=str(exc),
        )


def send_imessage(
    recipient: str,
    message: str,
    bluebubbles_config: dict[str, Any] | None = None,
) -> IMessageResult:
    """High-level dispatcher trying BlueBubbles if configured, otherwise native macOS."""
    if bluebubbles_config and bluebubbles_config.get("url") and bluebubbles_config.get("password"):
        import asyncio
        try:
            return asyncio.run(
                send_bluebubbles(
                    base_url=bluebubbles_config["url"],
                    password=bluebubbles_config["password"],
                    recipient=recipient,
                    message=message,
                )
            )
        except Exception as exc:
            logger.warning("BlueBubbles dispatch failed, falling back to native macOS: %s", exc)

    return send_native_applescript(recipient, message)
