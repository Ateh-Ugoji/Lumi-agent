"""Ports the native tools may use. A tool whose port is ``None`` is simply not registered."""

from __future__ import annotations

from dataclasses import dataclass

from lumi_ai.ports import (
    ConnectionLinks,
    ListeningStore,
    OwnPostSync,
    PostStore,
    ProfileStore,
    ReportStore,
    RepurposeStore,
    RequestStore,
    VoiceStore,
)


@dataclass(frozen=True, slots=True)
class ToolDeps:
    profiles: ProfileStore | None = None
    posts: PostStore | None = None
    voice: VoiceStore | None = None
    reports: ReportStore | None = None
    requests: RequestStore | None = None
    listening: ListeningStore | None = None
    repurpose: RepurposeStore | None = None
    links: ConnectionLinks | None = None
    post_sync: OwnPostSync | None = None
