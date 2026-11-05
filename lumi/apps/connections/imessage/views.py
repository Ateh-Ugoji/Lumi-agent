"""API Views for iMessage integration and channel control."""

from __future__ import annotations

import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.connections.imessage.client import (
    is_macos_native_available,
    send_imessage,
)
from apps.connections.imessage.service import handle_inbound_imessage
from apps.core.permissions import IsProfileOwner
from apps.core.throttles import ChatUserThrottle

logger = logging.getLogger(__name__)


class IMessageStatusView(APIView):
    """Returns status of native macOS iMessage and BlueBubbles bridges."""

    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]

    def get(self, request):
        native_avail = is_macos_native_available()
        return Response({
            "ok": True,
            "native_macos_available": native_avail,
            "channel": "native_macos" if native_avail else "bluebubbles_remote",
            "setup_guide": {
                "step_1": "Sign in to Apple Messages on this Mac with a dedicated Apple ID or your creator account.",
                "step_2": "Open iMessage on your iPhone and text that Apple ID or phone number.",
                "step_3": "Lumi detects incoming messages, invokes creator reasoning, and replies via blue bubbles.",
            },
        })


class IMessageSendView(APIView):
    """Sends a test or automated alert message via iMessage."""

    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]

    def post(self, request):
        data = request.data or {}
        recipient = data.get("recipient")
        message = data.get("message")
        if not recipient or not message:
            return Response(
                {"error": "Both 'recipient' and 'message' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bluebubbles_config = data.get("bluebubbles_config")
        result = send_imessage(
            recipient=recipient,
            message=message,
            bluebubbles_config=bluebubbles_config,
        )
        return Response({
            "ok": result.success,
            "channel": result.channel,
            "recipient": result.recipient,
            "error": result.error,
        })


class IMessageWebhookView(APIView):
    """Inbound webhook for incoming iMessage messages (e.g. from BlueBubbles or local watcher)."""

    def post(self, request):
        data = request.data or {}
        # Support BlueBubbles schema or generic inbound payload
        # BlueBubbles payload has: { "data": { "text": "...", "handle": { "address": "+1..." } } }
        sender = (
            data.get("sender")
            or data.get("from")
            or (data.get("data", {}).get("handle", {}).get("address") if isinstance(data.get("data"), dict) else None)
        )
        text = (
            data.get("text")
            or data.get("message")
            or (data.get("data", {}).get("text") if isinstance(data.get("data"), dict) else None)
        )

        if not sender or not text:
            return Response(
                {"error": "Sender and text are required in webhook payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile_id = data.get("profile_id")
        result = handle_inbound_imessage(
            sender=sender,
            text=text,
            profile_id=profile_id,
        )
        return Response(result, status=status.HTTP_200_OK if result["ok"] else status.HTTP_500_INTERNAL_SERVER_ERROR)
