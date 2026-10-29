"""Social listening and alert tools: start/stop polling, dismiss a trending alert."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from lumi_ai.ports import ListeningStore
from lumi_ai.tools.registry import ToolContext, ToolSpec

DEFAULT_INTERVAL_MINUTES = 5
MIN_INTERVAL_MINUTES = 1


def build(listening: ListeningStore) -> list[ToolSpec]:
    async def start_listening(
        ctx: ToolContext, interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    ) -> dict[str, Any]:
        minutes = max(MIN_INTERVAL_MINUTES, int(interval_minutes))
        config = await listening.get_listening(ctx.profile_id)
        saved = await listening.set_listening(
            replace(config, enabled=True, interval_minutes=minutes)
        )
        return {
            "profile_id": ctx.profile_id,
            "listening": saved.enabled,
            "interval_minutes": saved.interval_minutes,
        }

    async def stop_listening(ctx: ToolContext) -> dict[str, Any]:
        config = await listening.get_listening(ctx.profile_id)
        saved = await listening.set_listening(replace(config, enabled=False))
        return {"profile_id": ctx.profile_id, "listening": saved.enabled}

    async def dismiss_alert(ctx: ToolContext, post_id: int) -> dict[str, Any]:
        for alert in await listening.unread_alerts(ctx.profile_id):
            if alert.post_id == post_id:
                dismissed = await listening.dismiss_alert(ctx.profile_id, alert.id)
                return {"post_id": post_id, "dismissed": dismissed}
        return {"error": f"no unread alert for post {post_id}"}

    return [
        ToolSpec(
            name="start_listening",
            description="Start polling a profile's recent posts for engagement spikes ('trending' posts).",
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "integer"},
                    "interval_minutes": {"type": "integer"},
                },
                "required": ["profile_id"],
            },
            handler=start_listening,
            side_effects="writes_db",
            cache_ttl=0,
        ),
        ToolSpec(
            name="stop_listening",
            description="Stop polling a profile for trending posts.",
            parameters={
                "type": "object",
                "properties": {"profile_id": {"type": "integer"}},
                "required": ["profile_id"],
            },
            handler=stop_listening,
            side_effects="writes_db",
            cache_ttl=0,
        ),
        ToolSpec(
            name="dismiss_alert",
            description="Dismiss a trending-post alert without drafting a repurpose for it.",
            parameters={
                "type": "object",
                "properties": {"post_id": {"type": "integer"}},
                "required": ["post_id"],
            },
            handler=dismiss_alert,
            side_effects="writes_db",
            cache_ttl=0,
        ),
    ]
