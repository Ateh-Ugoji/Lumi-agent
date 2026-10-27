"""Niche keys. ``niche_key = "<slug>:<geo_scope>"``, geo scope being an ISO country or ``global``.

Only this survives from the legacy ``app/schemas/niche.py`` (~430 lines of evidence-mining models:
ScoredKeyword, GeoProfile, NicheLLMOutput, peer vetting...). Nothing in the legacy code ever
produced those models, and ``SCHEMA.md`` v2 stores a niche as ``niche_key``, ``title``, keywords
and tracked handles. The niche is deduced from the voice profile and from what the user says.
"""

from __future__ import annotations

import re
import unicodedata

GLOBAL_SCOPE = "global"
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_COUNTRY = re.compile(r"^[a-z]{2}$")


def slugify(text: str) -> str:
    """'AI tools for creators!' -> 'ai-tools-for-creators'. Empty when nothing usable remains."""
    ascii_text = (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return _NON_SLUG.sub("-", ascii_text).strip("-")[:60].strip("-")


def make_niche_key(niche: str, geo_scope: str | None = None) -> str:
    """Build a niche key. A scope that is not a two-letter country code means ``global``."""
    slug = slugify(niche)
    if not slug:
        raise ValueError("a niche key needs a niche with letters or digits")
    scope = (geo_scope or "").strip().lower()
    return f"{slug}:{scope if _COUNTRY.match(scope) else GLOBAL_SCOPE}"


def parse_niche_key(key: str) -> tuple[str, str]:
    """Split a niche key into ``(slug, geo_scope)``. Raises ``ValueError`` when malformed."""
    slug, sep, scope = key.partition(":")
    if not sep or not slug or slug != slugify(slug):
        raise ValueError(f"not a niche key: {key!r}")
    if scope != GLOBAL_SCOPE and not _COUNTRY.match(scope):
        raise ValueError(f"not a niche key: {key!r}")
    return slug, scope
