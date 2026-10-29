"""Scripted OpenAI-compatible clients for provider tests (test-only; never imported by lumi_ai)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai


def api_error(
    status: int, headers: dict[str, str] | None = None
) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request, headers=headers or {})
    return openai.APIStatusError(f"status {status}", response=response, body=None)


class FakeCreate:
    """``completions.create`` that raises or answers according to a script."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.models: list[str] = []
        self.efforts: list[str | None] = []

    async def __call__(self, *, model, messages, tools=None, reasoning_effort=None):
        self.models.append(model)
        self.efforts.append(reasoning_effort)
        action = self.script.pop(0) if self.script else "ok"
        if isinstance(action, Exception):
            raise action
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(model=model, usage=usage)


def fake_client(create: FakeCreate) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t
