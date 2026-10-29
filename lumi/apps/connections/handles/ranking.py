"""Pure ranking and mixing of handle rows."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .types import HandleRow

MIN_QUERY_LEN = 2
MIX_HALF = 5
MIX_TOTAL = 10
CONTEXT_WORDS = 3
DEFAULT_PLATFORM = "x"
# Same set as ``lumi_ai.ports.Platform`` and SCHEMA v2 (reddit left the schema, so a Reddit handle
# could not be stored in ``social_handles``).
PLATFORMS = ("x", "instagram", "tiktok", "linkedin", "facebook")


def normalize_query(raw: str) -> str:
    """Trim and drop the leading ``@``. Case is kept for display, see ``query_key``."""
    return (raw or "").strip().lstrip("@")


def query_key(raw: str) -> str:
    return normalize_query(raw).lower()


def parse_platforms(raw: str | Iterable[str] | None) -> list[str]:
    """Validated, deduplicated, ordered platforms. Empty or unknown input falls back to X."""
    parts = raw.split(",") if isinstance(raw, str) else list(raw or [])
    picked: list[str] = []
    for part in parts:
        name = str(part).strip().lower()
        if name in PLATFORMS and name not in picked:
            picked.append(name)
    return picked or [DEFAULT_PLATFORM]


def context_words(context: str) -> list[str]:
    """Up to three words typed before the mention. They re-rank and never reach the provider."""
    return [w for w in re.split(r"\W+", (context or "").lower()) if w][:CONTEXT_WORDS]


def clean_followers(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def rank(
    rows: Iterable[HandleRow],
    q_lower: str,
    *,
    db_keys: set[str],
    ctx_words: list[str],
) -> list[HandleRow]:
    """Order: exact handle, profile handles, context match, known followers, followers, handle."""

    def ctx_rank(r: HandleRow) -> int:
        if not ctx_words:
            return 1
        text = f"{r.handle} {r.display_name}".lower()
        return 0 if any(w in text for w in ctx_words) else 1

    return sorted(
        rows,
        key=lambda r: (
            0 if r.handle.lower() == q_lower else 1,
            0 if r.key in db_keys else 1,
            ctx_rank(r),
            0 if r.followers is not None else 1,
            -(r.followers or 0),
            r.handle.lower(),
        ),
    )


def mix(ranked: list[HandleRow], q_lower: str, *, db_keys: set[str]) -> list[HandleRow]:
    """Half saved, half live, with leftovers handed to the other side. Exact match first."""

    def is_saved(r: HandleRow) -> bool:
        return r.source != "live" or r.key in db_keys

    saved = [r for r in ranked if is_saved(r)]
    live = [r for r in ranked if not is_saved(r)]
    k = min(len(saved), MIX_HALF)
    o = min(len(live), MIX_HALF)
    deficit = MIX_TOTAL - (k + o)
    if deficit > 0:
        extra = min(deficit, len(saved) - k)
        k += extra
        deficit -= extra
        o += min(deficit, len(live) - o)
    mixed = saved[:k] + live[:o]
    for i, r in enumerate(mixed):
        if r.handle.lower() == q_lower:
            mixed.insert(0, mixed.pop(i))
            break
    return mixed[:MIX_TOTAL]
