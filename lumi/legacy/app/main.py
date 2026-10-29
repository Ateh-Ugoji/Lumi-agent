import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import neatlogs
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.background.mcp_refresh import run_mcp_refresh
from app.background.poller import run_poller
from app.routers import (
    alerts,
    chat,
    handles,
    mcp_google,
    pfm,
    profiles,
    repurpose,
    trends,
    voice,
)
from app.seed import seed_demo_profiles
from app.services.turn_metrics import recent_turn_latency


def _configure_app_logging() -> None:
    """Surface `app.*` INFO logs (turn timing, Jev gates) on stdout."""
    app_log = logging.getLogger("app")
    if app_log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)
    app_log.propagate = False


_configure_app_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Schema is managed by Alembic (`uv run alembic upgrade head`), not create_all().
    await seed_demo_profiles()

    try:
        from app.services.chroma import ensure_collections

        ready = ensure_collections()
        if ready:
            neatlogs.log("chroma collections ready", collections=ready)
    except Exception as exc:  # noqa: BLE001
        neatlogs.log("chroma init failed, continuing without agentic storage", error=str(exc))

    try:
        from app.services.framework_corpus import sync_frameworks_from_db

        indexed = await sync_frameworks_from_db()
        if indexed:
            neatlogs.log("chroma frameworks backfilled", count=indexed)
    except Exception as exc:  # noqa: BLE001
        neatlogs.log("chroma framework backfill failed", error=str(exc))

    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(run_poller(stop_event))
    # MCP `tools/list` discovery keeps the loop's cache warm in the
    # background — a turn never waits on it (PROMPT 5 item 6).
    mcp_refresh_task = asyncio.create_task(run_mcp_refresh(stop_event))

    yield

    stop_event.set()
    results = await asyncio.gather(
        poller_task, mcp_refresh_task, return_exceptions=True
    )
    for name, exc in zip(("poller", "mcp_refresh"), results):
        if isinstance(exc, BaseException):
            neatlogs.log(f"{name} task failed", error=str(exc))
    neatlogs.flush()
    neatlogs.shutdown()


app = FastAPI(title="Lumi", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(profiles.router)
app.include_router(alerts.router)
app.include_router(pfm.router)
app.include_router(trends.router)
app.include_router(handles.router)
app.include_router(voice.router)
app.include_router(mcp_google.router)
app.include_router(repurpose.router)



@app.get("/health")
async def health() -> dict:
    """Liveness + last-100 turn latency (PROMPT 5 item 8).

    The latency block is omitted whenever it cannot be computed (no
    classified turns yet, or any DB error), so the healthcheck itself can
    never fail on it — missing metrics stay absent, never 0.
    """
    payload: dict = {"status": "ok"}
    payload.update(await recent_turn_latency())
    return payload
