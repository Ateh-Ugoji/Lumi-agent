"""Deterministic checks that need no model: platform limits, required phrases, links, hashtags, AI tells.

The platform and request rules are the ones of ``generation.enforcement``; this adds the style
patterns the author never wants to see. The tell list is English only and short on purpose:
every entry is a phrase that readers already associate with machine-written posts.
"""

from __future__ import annotations

import re

from lumi_ai.generation.enforcement import deterministic_failures
from lumi_ai.generation.types import GenerationBrief

EM_DASH = "\u2014"
_TELLS = (
    r"in today'?s (?:fast[- ]paced|digital|ever[- ]changing) (?:world|landscape)",
    r"let'?s dive in",
    r"\bdelve\b",
    r"unlock the (?:power|potential)",
    r"game[- ]changer",
    r"as an ai\b",
    r"i hope this (?:helps|finds you)",
    r"here'?s the thing:?",
)
_TELL = re.compile("|".join(_TELLS), re.IGNORECASE)
_FENCE = re.compile(r"```|^\s*\{\s*\"text\"", re.MULTILINE)


def forbidden_patterns(text: str) -> list[str]:
    """Style patterns the post must not contain."""
    found: list[str] = []
    if EM_DASH in text:
        found.append(
            "contains an em dash (\u2014); use a comma, a period or parentheses"
        )
    tell = _TELL.search(text)
    if tell:
        found.append(f"contains the stock phrase {tell.group(0)!r}")
    if _FENCE.search(text):
        found.append("contains a code fence or leaked JSON")
    return found


def all_failures(brief: GenerationBrief, text: str) -> list[str]:
    return [*deterministic_failures(brief, text), *forbidden_patterns(text)]
