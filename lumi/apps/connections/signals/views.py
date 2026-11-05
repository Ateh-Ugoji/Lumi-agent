"""Views for ingesting and testing post signal webhooks."""

from __future__ import annotations

import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.connections.signals.dispatcher import SignalEvent, dispatch_signal_alert
from apps.core.permissions import IsProfileOwner
from apps.core.throttles import ChatUserThrottle

logger = logging.getLogger(__name__)


class SignalWebhookView(APIView):
    """Inbound webhook to receive post engagement signals and trigger alerts."""

    def post(self, request):
        data = request.data or {}
        event_type = data.get("event_type") or data.get("event") or "spike.velocity"
        title = data.get("title") or "Post Signal Detected"
        message = data.get("message") or ""
        event_data = data.get("data") or {}

        signal = SignalEvent(
            event_type=event_type,
            title=title,
            message=message,
            data=event_data,
        )

        imessage_recipient = data.get("imessage_recipient")
        webhook_url = data.get("webhook_url")

        result = dispatch_signal_alert(
            signal=signal,
            imessage_recipient=imessage_recipient,
            webhook_url=webhook_url,
        )

        return Response({
            "ok": True,
            "signal": event_type,
            "dispatched": result,
        }, status=status.HTTP_200_OK)


class SignalTestView(APIView):
    """Allows testing signal notifications directly from Lumi dashboard."""

    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]

    def post(self, request):
        data = request.data or {}
        event_type = data.get("event_type") or "spike.velocity"
        recipient = data.get("imessage_recipient")

        test_payloads = {
            "spike.velocity": {
                "url": "https://x.com/creator/status/123456789",
                "velocity": "4.2x",
                "replies": 84,
            },
            "author.golden_hour": {},
            "competitor.breakout": {
                "handle": "honour_can_code",
                "hook": "90% of developers use AI wrong. Here is the 3-step loop:",
                "lift": "3.8x",
            },
            "tweepcred.degraded": {
                "ratio": "0.68",
                "division_factor": "2.4x",
            },
        }

        signal = SignalEvent(
            event_type=event_type,
            title=f"Test {event_type}",
            message="Test dispatch from Lumi",
            data=test_payloads.get(event_type, {}),
        )

        result = dispatch_signal_alert(signal=signal, imessage_recipient=recipient)
        return Response({
            "ok": True,
            "test_result": result,
        })
