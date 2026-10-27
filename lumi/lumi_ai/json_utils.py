"""Robust JSON extraction from model output.

The legacy code removed code fences with ``raw.strip("`")``, which also eats backticks that
belong to the content and cannot cope with prose around the JSON. ``extract_json`` finds the
first balanced JSON value instead.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n?(.*?)```", re.DOTALL)


class JSONExtractionError(ValueError):
    """No valid JSON value could be found in the text."""


def _balanced_slice(text: str, start: int) -> str | None:
    """Return the balanced ``{...}`` or ``[...]`` that starts at ``start``, or ``None``."""
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _candidates(text: str) -> list[str]:
    """Texts to try, most specific first: fenced blocks, then the raw text."""
    found = [m.group(1).strip() for m in _FENCE_RE.finditer(text)]
    found.append(text.strip())
    return [c for c in found if c]


def extract_json(text: str) -> Any:
    """Return the first JSON object or array found in ``text``.

    Handles code fences (with or without a language tag), prose before and after the JSON,
    and braces inside strings. Raises :class:`JSONExtractionError` when nothing parses.
    """
    if not text or not text.strip():
        raise JSONExtractionError("empty model output")
    for candidate in _candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        for i, ch in enumerate(candidate):
            if ch not in "{[":
                continue
            piece = _balanced_slice(candidate, i)
            if piece is None:
                continue
            try:
                return json.loads(piece)
            except json.JSONDecodeError:
                continue
    raise JSONExtractionError("no valid JSON value in model output")


def extract_json_object(text: str) -> dict[str, Any]:
    """Like :func:`extract_json` but the value must be an object."""
    value = extract_json(text)
    if not isinstance(value, dict):
        raise JSONExtractionError(f"expected a JSON object, got {type(value).__name__}")
    return value
