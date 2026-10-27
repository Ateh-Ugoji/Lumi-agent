import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime

import neatlogs
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select

from app.agent.loop import run_agent_loop
from app.database import session_scope
from app.models.chat import ChatMessage, ChatRole

router = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 50


class ChatRequest(BaseModel):
    profile_id: int
    message: str


class ChatResponse(BaseModel):
    role: str = "assistant"
    content: str
    tool_calls_made: list[str]
    tool_executions: list[dict] = []


class ChatHistoryMessage(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    messages: list[ChatHistoryMessage]


@router.post("", response_model=ChatResponse)
async def send_chat_message(payload: ChatRequest) -> ChatResponse:
    result = await run_agent_loop(payload.profile_id, payload.message)
    return ChatResponse(
        content=result.content,
        tool_calls_made=result.tool_calls_made,
        tool_executions=result.tool_executions,
    )


@router.post("/stream")
async def stream_chat_message(payload: ChatRequest) -> StreamingResponse:
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_step(event: dict) -> None:
        await queue.put(event)

    async def runner():
        try:
            result = await run_agent_loop(payload.profile_id, payload.message, on_step=on_step)
            await queue.put({"type": "done", "content": result.content, "tool_executions": result.tool_executions})
        except Exception as e:
            # Server-side record of the failure: the SSE consumer only sees the
            # message, so without this a dead turn leaves no trace in the logs.
            logger.exception("agent stream failed (profile %s)", payload.profile_id)
            await queue.put({"type": "error", "error": str(e) or type(e).__name__})
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                event = await queue.get()

                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            # Client disconnected or the generator was closed early: stop the
            # agent loop instead of letting it run to completion unsupervised
            # (LLM calls, tool calls, DB writes) for a response no one reads.
            if not task.done():
                task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")




@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    profile_id: int, limit: int = DEFAULT_HISTORY_LIMIT, before: int | None = None
) -> ChatHistoryResponse:
    async with session_scope() as session:
        query = (
            select(ChatMessage)
            .where(ChatMessage.profile_id == profile_id, ChatMessage.role != ChatRole.TOOL)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        if before is not None:
            query = query.where(ChatMessage.id < before)

        messages = (await session.exec(query)).all()

    ordered = sorted(messages, key=lambda m: m.id)
    return ChatHistoryResponse(
        messages=[
            ChatHistoryMessage(id=m.id, role=m.role.value, content=m.content, created_at=m.created_at)
            for m in ordered
        ]
    )


@router.delete("/history")
async def clear_chat_history(profile_id: int) -> dict:
    async with session_scope() as session:
        messages = (await session.exec(select(ChatMessage).where(ChatMessage.profile_id == profile_id))).all()
        for m in messages:
            await session.delete(m)
        await session.commit()
    return {"status": "ok", "deleted_count": len(messages)}


class ChatTitleRequest(BaseModel):
    message: str


class ChatTitleResponse(BaseModel):
    title: str


@router.post("/title", response_model=ChatTitleResponse)
@neatlogs.span(kind="CHAIN", name="generate_chat_title")
async def generate_chat_title(payload: ChatTitleRequest) -> ChatTitleResponse:
    from app.agent.providers import chat_completion_with_fallback

    prompt = (
        "Generate a concise, title-cased summary title (2 to 4 words maximum, no punctuation, no quotes, no markdown) "
        f"for a creator chat that begins with this user message: \"{payload.message}\". "
        "Output ONLY the 2 to 4 word title."
    )
    try:
        completion = await chat_completion_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            tools=[],
        )
        raw_title = (completion.choices[0].message.content or "").strip().strip('"').strip("'")
        raw_title = raw_title.replace("**", "").replace("#", "").replace(".", "").strip()
        if not raw_title or len(raw_title) > 35:
            words = payload.message.strip().split()
            raw_title = " ".join(words[:4]).title()
        return ChatTitleResponse(title=raw_title)
    except Exception:  # noqa: BLE001
        words = payload.message.strip().split()
        fallback = " ".join(words[:4]).title()
        return ChatTitleResponse(title=fallback or "New Chat")


