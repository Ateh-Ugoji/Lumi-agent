"""``HandleBook`` over CONNECT's ``HandleDirectory`` (the replacement of the legacy handle_db).

The directory is built with no exact-user lookup and ``enrich_limit=0``: a scan saves handles and
pictures it already has and never spends a paid call. Its methods do not raise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from apps.connections.handles.directory import HandleDirectory
from apps.connections.handles.types import HandleRow
from apps.connections.stores import DjangoHandleStore
from lumi_ai.ports import KnownHandle, Platform


class HandleBookRepo:
    def __init__(self, directory: HandleDirectory | None = None) -> None:
        self._directory = directory or HandleDirectory(DjangoHandleStore())

    async def remember_scanned(
        self, platform: Platform, handles: Sequence[str], *, origin: str
    ) -> int:
        return await self._directory.remember_scanned(
            handles, origin=origin, platform=platform
        )

    async def remember(
        self, platform: Platform, handles: Sequence[KnownHandle], *, origin: str
    ) -> int:
        rows = [
            HandleRow(handle=h.handle, platform=platform, avatar_url=h.avatar_url)
            for h in handles
        ]
        return await self._directory.remember(rows, origin=origin, platform=platform)

    async def pictures(
        self, platform: Platform, handles: Sequence[str]
    ) -> Mapping[str, str]:
        found = await self._directory.pictures(handles, platform=platform)
        return {handle: pic.avatar_url for handle, pic in found.items()}
