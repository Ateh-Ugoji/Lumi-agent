"""End-of-turn memory: pull durable facts out of one exchange and refresh the rolling summary.

Satisfies ``agent.loop.MemoryExtractor``. The loop runs it in the background after the reply, so a
failure here never reaches the user; it raises ``MemoryExtractionError`` and the loop logs it.
"""

from __future__ import annotations

import logging
from typing import Any

from lumi_ai.agent.support import Completer
from lumi_ai.config import AIConfig
from lumi_ai.json_utils import JSONExtractionError, extract_json_object
from lumi_ai.ports import MemoryStore
from lumi_ai.rag.memory import MemoryService

logger = logging.getLogger(__name__)

PROMPT_VERSION = "memory-v2"

SYSTEM = """\
You maintain an agent's long-term memory for a social-media creator profile.
You receive the previous rolling summary plus one new conversation turn.

Return ONLY a JSON object:
{
  "memories": ["short durable fact worth storing individually", ...],
  "summary": "the complete updated rolling summary as markdown bullets, one per line, each starting with '- '"
}

Rules:
- memories: only durable, specific facts (preferences, decisions, project details, recurring context).
  Never include pleasantries, transient requests, or anything already implied by the summary.
  Write each one as a standalone sentence that makes sense without the conversation.
- summary: merge the prior summary with anything new. Drop stale or contradicted items.
  Keep it tight (ideally under 15 bullets). It is the ONLY context the agent will have next session.
- If nothing changed: "memories": [] and return the prior summary unchanged.
"""


class MemoryExtractionError(RuntimeError):
    """The model did not return a usable memory update."""


def clean_summary(raw: str) -> str:
    """Strip fences and a stray ``## Profile`` header the model sometimes echoes."""
    lines = [
        line.rstrip()
        for line in raw.strip().strip("`").strip().splitlines()
        if not line.lstrip().startswith("## Profile")
    ]
    return "\n".join(lines).strip()


class LLMMemoryExtractor:
    def __init__(
        self,
        llm: Completer,
        service: MemoryService,
        store: MemoryStore,
        config: AIConfig,
    ):
        self._llm = llm
        self._service = service
        self._store = store
        self._cfg = config

    async def extract(self, profile_id: int, user_message: str, reply: str) -> None:
        prior = await self._store.get_summary(profile_id)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": (
                    f"PRIOR SUMMARY:\n{prior or '(empty)'}\n\n"
                    f"NEW TURN:\nUser: {user_message}\n\nAssistant: {reply}"
                ),
            },
        ]
        result = await self._llm.complete(messages, [], tier="small", effort="low")
        raw = result.completion.choices[0].message.content or ""
        try:
            data = extract_json_object(raw)
        except JSONExtractionError as exc:
            raise MemoryExtractionError(f"no usable JSON: {exc}") from exc

        raw_memories = data.get("memories") or []
        if not isinstance(raw_memories, list):
            raise MemoryExtractionError("`memories` must be a list")
        facts = [
            " ".join(str(m).split())
            for m in raw_memories
            if isinstance(m, str) and m.strip()
        ][: self._cfg.memory_max_per_turn]
        for fact in facts:
            outcome = await self._service.remember(profile_id, fact, kind="extracted")
            if outcome.status == "too_long":
                logger.info("memory fact skipped, too long: %.60s…", fact)

        summary = clean_summary(str(data.get("summary") or ""))
        if summary and summary != prior.strip():
            await self._store.set_summary(
                profile_id, summary[: self._cfg.memory_summary_max_chars]
            )
