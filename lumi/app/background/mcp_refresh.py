"""Background MCP `tools/list` refresh (PROMPT 5 item 6).

A turn must NEVER wait on connector discovery, so the agent loop only reads
the cached specs (`mcp.list_specs()`) and this task is what keeps that cache
warm. `mcp.refresh_tools()` is itself TTL-gated (`MCP_TOOLS_TTL_SECONDS`,
default 300s), so waking more often than the TTL costs a monotonic-clock
comparison, not a network call.

Cold start: the first refresh runs as soon as this task starts, so the cache
is populated within ~1s of boot. A turn that lands inside that window simply
runs without the connector's tools (exactly like an unauthenticated
connector) — a turn never waits on discovery, by design.
"""

import asyncio
import logging

from app.config import get_settings
from app.services import mcp as mcp_service

logger = logging.getLogger("app.mcp_refresh")

# How often the task wakes to look at the cache. The TTL gate inside
# refresh_tools decides whether a wake reaches the network, so a short tick
# only bounds how stale a just-expired cache can get (<= 30s).
TICK_SECONDS = 30.0
# Never spin tighter than this, whatever the TTL is configured to.
MIN_TICK_SECONDS = 5.0


def _tick_seconds() -> float:
    """Wake interval: never busier than TICK, never tighter than the floor."""
    try:
        ttl = float(get_settings().mcp_tools_ttl_seconds)
    except Exception:  # noqa: BLE001 - config trouble must not kill the task
        return TICK_SECONDS
    return max(MIN_TICK_SECONDS, min(TICK_SECONDS, ttl))


async def run_mcp_refresh(stop_event: asyncio.Event) -> None:
    """Refresh connector tool caches until `stop_event` is set. Never raises."""
    while not stop_event.is_set():
        try:
            await mcp_service.refresh_tools()
        except Exception as exc:  # noqa: BLE001 - belt and braces; it never raises
            logger.warning("mcp background refresh failed: %s", exc)
        try:
            # Interruptible sleep: shutdown wakes the task immediately.
            await asyncio.wait_for(stop_event.wait(), timeout=_tick_seconds())
        except TimeoutError:
            continue
