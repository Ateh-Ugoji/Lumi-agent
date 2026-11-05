"""Optional tracing through neatlogs.

Nothing in ``lumi_ai`` requires neatlogs. When ``neatlogs_api_key`` is empty, every function here
does nothing; when it is set, the SDK is imported lazily, so ``import lumi_ai`` never needs it.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

from lumi_ai.config import AIConfig

logger = logging.getLogger(__name__)

NEATLOGS_ENDPOINT = "https://ingest.neatlogs.com"
NEATLOGS_WORKFLOW_NAME = "lumi"

_sdk: Any | None = None


def init_tracing(config: AIConfig) -> bool:
    """Start neatlogs when a key is configured. Returns whether tracing is on. Never raises."""
    global _sdk
    if not config.neatlogs_api_key:
        return False
    if _sdk is not None:
        return True
    try:
        import neatlogs

        neatlogs.init(
            api_key=config.neatlogs_api_key,
            endpoint=NEATLOGS_ENDPOINT,
            workflow_name=NEATLOGS_WORKFLOW_NAME,
            capture_logs=True,
        )
    except Exception:
        logger.warning("neatlogs could not start; tracing is off", exc_info=True)
        return False
    _sdk = neatlogs
    return True


def wrap_client(client: Any, provider: str) -> Any:
    """Return the client wrapped for tracing, or the same client when tracing is off."""
    if _sdk is None:
        return client
    try:
        return _sdk.wrap(client, provider=provider)
    except Exception:
        logger.warning(
            "neatlogs could not wrap %s; using the plain client",
            provider,
            exc_info=True,
        )
        return client


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """Trace a block. A plain pass-through when tracing is off."""
    if _sdk is None:
        yield
        return
    try:
        cm = _sdk.span(name, **attributes)
    except Exception:  # noqa: BLE001
        yield
        return
    with cm:
        yield


def log_event(message: str, **fields: Any) -> None:
    """Send a structured event to neatlogs, or do nothing when it is off."""
    if _sdk is None:
        return
    try:
        _sdk.log(message, **fields)
    except Exception:
        logger.debug("neatlogs log failed", exc_info=True)


def flush_and_shutdown() -> None:
    """Flush pending spans at process exit."""
    global _sdk
    if _sdk is None:
        return
    with contextlib.suppress(Exception):
        _sdk.flush()
        _sdk.shutdown()
    _sdk = None
