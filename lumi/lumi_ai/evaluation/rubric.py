"""The six-criterion rubric and the scorers that apply it: Jev first, a small LLM second.

Both return ``None`` when they have no complete answer (a partial verdict is no verdict), so
the evaluator can move on and, in the end, say honestly that only rules ran.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from lumi_ai.agent.support import Completer
from lumi_ai.evaluation.types import JudgeName, RubricResult
from lumi_ai.generation.platforms import PlatformRules
from lumi_ai.generation.types import GenerationBrief
from lumi_ai.json_utils import JSONExtractionError, extract_json_object
from lumi_ai.ports import SemanticJudge

log = logging.getLogger(__name__)

CRITERIA: dict[str, str] = {
    "voice_fidelity": "Does the post sound like the author's own example posts (tone, vocabulary, rhythm) rather than generic copy?",
    "platform_fit": "Does the post follow the conventions of the target platform (length, format, openers, hashtags, links)?",
    "hook": "Does the first line make a reader want to continue, without clickbait or a generic opener?",
    "specificity": "Does the post say concrete things (names, numbers, examples, a clear point) instead of vague generalities?",
    "no_ai_tells": "Is the post free of the marks of machine-written text (stock phrases, empty enthusiasm, symmetrical lists, filler)?",
    "no_invented_facts": "Does the post avoid stating facts, numbers, quotes or events that the source or the brief did not provide?",
}
GUIDANCE: dict[str, str] = {
    "voice_fidelity": "match the author's tone, vocabulary and rhythm as shown in the voice and examples",
    "platform_fit": "follow the platform's length, format and hashtag conventions",
    "hook": "open with a first line that earns the next one",
    "specificity": "replace vague claims with concrete details that the source supports",
    "no_ai_tells": "remove stock phrases and filler; write the way the author talks",
    "no_invented_facts": "remove every fact, number or event that the source does not contain",
}
CRITICAL = "no_invented_facts"


class RubricScorer(Protocol):
    name: JudgeName

    async def score(
        self,
        brief: GenerationBrief,
        text: str,
        rules: PlatformRules,
        examples: Sequence[str],
    ) -> RubricResult | None: ...


def _state(
    brief: GenerationBrief, text: str, rules: PlatformRules, examples: Sequence[str]
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "post": text,
        "target_platform": rules.label,
        "platform_guidance": rules.guidance,
        "author_example_posts": list(examples),
    }
    if brief.mode == "repurpose":
        state["source_caption"] = brief.source_text
    else:
        state["topic"] = brief.topic
        if brief.source_text:
            state["reference_material"] = brief.source_text
    return state


def _band(score: float) -> str:
    return "strong" if score >= 0.7 else "weak" if score >= 0.5 else "poor"


class JevScorer:
    """Scores through the semantic judge (Jev, via the SemanticJudge port). Numbers only."""

    name: JudgeName = "jev"

    def __init__(self, judge: SemanticJudge) -> None:
        self._judge = judge

    async def score(self, brief, text, rules, examples) -> RubricResult | None:
        raw = await self._judge.ask_noul(
            _state(brief, text, rules, examples), dict(CRITERIA)
        )
        if raw is None:
            return None
        scores: dict[str, float] = {}
        for name in CRITERIA:
            try:
                scores[name] = min(1.0, max(0.0, float(raw[name])))
            except (KeyError, TypeError, ValueError):
                return None
        reasons = {n: f"judge score {s:.2f} ({_band(s)})" for n, s in scores.items()}
        return RubricResult(scores, reasons, self.name)


_SYSTEM = (
    "You are a strict editor scoring one social post. Score each criterion from 0.0 (clearly fails) "
    "to 1.0 (clearly meets it). Be critical: most drafts have a weakness. Give a reason of at most "
    "20 words that names what is wrong or right in THIS post.\n"
    'Reply with ONE JSON object: {"<criterion>": {"score": 0.0, "reason": "..."}, ...} '
    "with exactly these keys: "
    + ", ".join(CRITERIA)
    + ".\n\nCRITERIA\n"
    + "\n".join(f"- {n}: {q}" for n, q in CRITERIA.items())
)


class LLMScorer:
    """Scores and explains through the small model of the provider chain."""

    name: JudgeName = "groq-small"

    def __init__(self, llm: Completer, *, tier: str = "small") -> None:
        self._llm = llm
        self._tier = tier

    async def score(self, brief, text, rules, examples) -> RubricResult | None:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    _state(brief, text, rules, examples), ensure_ascii=False
                ),
            },
        ]
        try:
            result = await self._llm.complete(
                messages, [], tier=self._tier, effort="low"
            )
            data = extract_json_object(
                result.completion.choices[0].message.content or ""
            )
            return parse_rubric(data, self.name)
        except JSONExtractionError as exc:
            log.warning("rubric scorer returned unparseable output: %s", exc)
        except Exception as exc:  # noqa: BLE001 - scoring is best-effort; the evaluator reports "rules"
            log.warning("rubric scorer failed: %s", exc)
        return None


def parse_rubric(data: Mapping[str, Any], source: JudgeName) -> RubricResult | None:
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for name in CRITERIA:
        item = data.get(name)
        if not isinstance(item, Mapping):
            return None
        try:
            scores[name] = min(1.0, max(0.0, float(item["score"])))
        except (KeyError, TypeError, ValueError):
            return None
        reasons[name] = (
            str(item.get("reason") or "").strip() or f"score {scores[name]:.2f}"
        )
    return RubricResult(scores, reasons, source)
