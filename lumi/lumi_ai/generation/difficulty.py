"""How hard a rewrite is, which decides the model tier of the first attempt.

Jev answers first; the rule runs only when Jev has no answer. Both are generalized from the
legacy code, which knew only the X limit and treated every other platform as 'standard'.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from lumi_ai.generation.platforms import measure, rules_for
from lumi_ai.generation.types import Difficulty
from lumi_ai.ports import SemanticJudge, Tier

ROUTE_TIERS: Final[dict[str, Tier]] = {
    "easy": "small",
    "standard": "large",
    "hard": "large",
}
HARD_PROTECTED_ITEMS = 3
PROTECTED_TOKEN = re.compile(r"https?://\S+|@\w+")

CRITERIA: Final[dict[str, str]] = {
    "easy": "Light restyle: the caption already fits the target platform's length and nothing has to survive verbatim.",
    "standard": "Moderate rewrite: a different platform or length, or one or two links, @handles or required phrases to keep.",
    "hard": (
        "Heavily constrained: the caption must be compressed to fit the platform's limit, "
        "or many links, @handles, numbers or required phrases must survive intact."
    ),
}


def protected_tokens(text: str) -> list[str]:
    """URLs and @mentions of ``text`` as they must appear in the rewrite (no trailing punctuation)."""
    return [t.rstrip(".,;:!?)]}\"'") for t in PROTECTED_TOKEN.findall(text)]


def classify_by_rule(
    source_text: str, platform: str, must_keep: Sequence[str]
) -> Difficulty:
    rules = rules_for(platform)
    length = measure(platform, source_text)
    protected = len(must_keep) + len(protected_tokens(source_text))
    if length > rules.hard_limit or protected >= HARD_PROTECTED_ITEMS:
        return "hard"
    if protected == 0 and rules.target_min <= length <= rules.target_max:
        return "easy"
    return "standard"


async def classify_difficulty(
    judge: SemanticJudge | None,
    source_text: str,
    platform: str,
    must_keep: Sequence[str],
) -> Difficulty:
    """Jev (or whichever judge answers) first, the deterministic rule when nobody answers."""
    if judge is not None:
        rules = rules_for(platform)
        choice = await judge.ask_choice(
            {
                "source_caption": source_text,
                "source_length": len(source_text),
                "target_platform": rules.platform,
                "target_length_limit": rules.hard_limit,
                "target_recommended_length": [rules.target_min, rules.target_max],
                "must_keep_phrases": list(must_keep),
            },
            "difficulty",
            "How hard is it to rewrite this caption for the target platform?",
            CRITERIA,
        )
        if choice in CRITERIA:
            return choice  # type: ignore[return-value]
    return classify_by_rule(source_text, platform, must_keep)
