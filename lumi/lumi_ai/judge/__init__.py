"""The semantic judge: Jev first, the small LLM second; callers keep a deterministic last resort."""

from __future__ import annotations

from lumi_ai.config import AIConfig
from lumi_ai.judge.jev import JevJudge
from lumi_ai.judge.llm import FallbackJudge, LLMJudge
from lumi_ai.ports import SemanticJudge
from lumi_ai.providers.chain import LLMChain


def build_judge(config: AIConfig, chain: LLMChain | None = None) -> SemanticJudge:
    """Jev (if keyed), then the small-tier LLM (if a chain exists). May always answer ``None``."""
    judges: list[SemanticJudge] = []
    jev = JevJudge(config)
    if jev.available:
        judges.append(jev)
    if chain is not None:
        judges.append(LLMJudge(chain))
    return FallbackJudge(*judges)


__all__ = ["FallbackJudge", "JevJudge", "LLMJudge", "build_judge"]
