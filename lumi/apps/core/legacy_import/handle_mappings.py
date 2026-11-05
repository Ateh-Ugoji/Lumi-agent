"""Legacy handle picks (``--handle-mappings``) to ``connections.UserSavedHandle``.

The legacy SQLite has no table of saved or selected handles. The legacy app kept them in
Chroma Cloud, collection ``handle_mappings``, one entry per ``<platform>:<handle>`` with the
metadata ``handle, platform, display_name, avatar_url, followers (-1 unknown), selected_query,
origin (selected | live | cache), ts (epoch seconds)``. A pick wrote ``origin="selected"``; a
later live pull of the same handle overwrote it.

The legacy app was single-user, so every pick belongs to the ``--user`` target. The operator
exports the collection (``collection.get(include=["metadatas"])``, dumped as JSON) and passes it
with ``--handle-mappings``. The own profiles of the SQLite ``profiles`` table are *not* picks:
``GET /handles/saved`` already reads them from ``social_profiles``.

Everything here is ARCHITECT's. ``UserSavedHandle`` is written through its model, never through
CONNECT's importer or store. Models are imported inside functions: this package loads before
the app registry is ready.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.core.legacy_import.engine import (
    IMPORTED_EMAIL,
    ImportContext,
    Importer,
    VerifyRow,
    register,
)

TABLE = "user_saved_handles"
SOURCE = "handle_mappings"
PICK_ORIGIN = "selected"


class HandleMappingsError(ValueError):
    """The ``--handle-mappings`` file is not a Chroma export this importer understands."""


@dataclass(frozen=True)
class Pick:
    platform: str
    handle: str
    normalized: str
    display_name: str
    avatar_url: str
    followers: int | None
    saved_at: datetime | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.platform, self.normalized)


@dataclass
class Picks:
    read: int  # entries with origin "selected"
    unique: list[Pick]  # one per (platform, handle), the earliest save wins
    merged: int  # repeated entries of the same (platform, handle)
    unusable: list[str]  # why an entry cannot be stored (unknown platform, bad handle)


def _entries(data: Any) -> list[dict[str, Any]]:
    """Chroma ``get`` result (``{"ids": [...], "metadatas": [...]}``) or a bare list."""
    if isinstance(data, dict):
        data = data.get("metadatas")
    if not isinstance(data, list):
        raise HandleMappingsError(
            "el archivo no es un export de handle_mappings: se esperaba una lista de "
            'metadatos o {"metadatas": [...]}'
        )
    return [m for m in data if isinstance(m, dict)]


def _epoch(value: Any) -> datetime | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def read_picks(path: str) -> Picks:
    from apps.profiles.services import InvalidHandle, clean_avatar_url, normalize_handle

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise HandleMappingsError(f"{path}: JSON no válido ({exc})") from exc
    picks: dict[tuple[str, str], Pick] = {}
    read = merged = 0
    unusable: list[str] = []
    for meta in _entries(data):
        if str(meta.get("origin") or "").lower() != PICK_ORIGIN:
            continue
        read += 1
        platform = str(meta.get("platform") or "x").strip().lower()
        raw = str(meta.get("handle") or "")
        try:
            normalized = normalize_handle(platform, raw)
        except InvalidHandle:
            unusable.append(f"{platform}:{raw!r}: red o handle no válidos")
            continue
        followers = meta.get("followers")
        pick = Pick(
            platform=platform,
            handle=raw.strip().lstrip("@")[:100],
            normalized=normalized,
            display_name=str(meta.get("display_name") or "")[:200],
            avatar_url=clean_avatar_url(str(meta.get("avatar_url") or "")) or "",
            followers=followers
            if isinstance(followers, int)
            and not isinstance(followers, bool)
            and followers >= 0
            else None,
            saved_at=_epoch(meta.get("ts")),
        )
        seen = picks.get(pick.key)
        if seen is None:
            picks[pick.key] = pick
            continue
        merged += 1
        first, other = (
            (pick, seen)
            if pick.saved_at
            and (seen.saved_at is None or pick.saved_at < seen.saved_at)
            else (seen, pick)
        )
        # The earliest save gives the date; a card field it lacks comes from the other entry.
        picks[pick.key] = replace(
            first,
            display_name=first.display_name or other.display_name,
            avatar_url=first.avatar_url or other.avatar_url,
            followers=first.followers
            if first.followers is not None
            else other.followers,
            saved_at=first.saved_at or other.saved_at,
        )
    return Picks(read, list(picks.values()), merged, unusable)


def import_saved_handles(ctx: ImportContext) -> None:
    """One ``user_saved_handles`` row per legacy pick, owned by ``ctx.user``. Idempotent."""
    if not ctx.handle_mappings:
        return  # the SQLite holds no picks and no file was given: nothing to do
    from apps.connections.models import UserSavedHandle
    from apps.profiles import services

    picks = read_picks(ctx.handle_mappings)
    report = ctx.table(TABLE)
    report.read = picks.read
    report.merged = picks.merged
    report.skipped = len(picks.unusable)
    for why in picks.unusable:
        ctx.warn(f"{SOURCE} {why}, no se guarda")
    for pick in picks.unique:
        handle_id = services.get_or_create_handle(
            pick.platform,
            pick.handle,
            origin=PICK_ORIGIN,
            display_name=pick.display_name,
            avatar_url=pick.avatar_url,
            handle_display=pick.handle,
        )
        if pick.followers is not None and pick.saved_at is not None:
            # Dated at the legacy save, so a re-run writes the same reading and a newer
            # one already on the handle stays the current one.
            services.record_handle_snapshot(
                handle_id, followers=pick.followers, captured_at=pick.saved_at
            )
        row, created = UserSavedHandle.objects.get_or_create(
            user=ctx.user,
            handle_id=handle_id,
            defaults={"created_at": pick.saved_at} if pick.saved_at else {},
        )
        if created:
            report.imported += 1
            continue
        report.already += 1
        if pick.saved_at and row.created_at > pick.saved_at:
            # The user picked it again before the import ran: keep the original date.
            UserSavedHandle.objects.filter(pk=row.pk).update(created_at=pick.saved_at)


def verify_saved_handles(path: str, user_email: str | None) -> VerifyRow:
    """``ok`` only when every usable legacy pick is in ``user_saved_handles`` for that user."""
    from apps.accounts.models import User
    from apps.connections.models import UserSavedHandle

    picks = read_picks(path)
    user = User.objects.filter(
        email=(user_email or IMPORTED_EMAIL).strip().lower()
    ).first()
    saved: set[tuple[str, str]] = set()
    if user is not None:
        saved = set(
            UserSavedHandle.objects.filter(user=user).values_list(
                "handle__platform", "handle__handle_normalized"
            )
        )
    present = sum(1 for p in picks.unique if p.key in saved)
    skipped = len(picks.unusable)
    return VerifyRow(
        f"{TABLE} ({SOURCE})",
        picks.read,
        present + picks.merged + skipped,
        "ok" if present == len(picks.unique) else "difiere",
        imported=present,
        merged=picks.merged,
        skipped=skipped,
    )


register(Importer("saved_handles", (), 75, import_saved_handles))
