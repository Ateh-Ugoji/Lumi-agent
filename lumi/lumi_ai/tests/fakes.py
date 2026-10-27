"""In-memory implementations of the ports, for tests only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from lumi_ai.ports import (
    ActivityOut,
    AlertOut,
    ChatMessageIn,
    ChatMessageOut,
    ConnectLink,
    ListeningConfig,
    McpCallResult,
    McpPendingResolution,
    McpToolSpec,
    MemoryNoteOut,
    PeerPostOut,
    PostMetrics,
    PostOut,
    StyleAnswerIn,
    UserRequestOut,
    VoiceProfileOut,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def make_post(
    pid: int,
    text: str = "hello",
    *,
    views: int | None = 100,
    likes: int | None = 10,
    days_ago: int = 1,
    kind: str | None = "original",
    profile_id: int = 1,
    platform: str = "x",
) -> PostOut:
    return PostOut(
        id=pid,
        profile_id=profile_id,
        platform=platform,  # type: ignore[arg-type]
        external_id=f"ext{pid}",
        text=text,
        published_at=NOW - timedelta(days=days_ago),
        kind=kind,  # type: ignore[arg-type]
        metrics=PostMetrics(views=views, likes=likes, bookmarks=2 if views else None),
    )


class FakePosts:
    def __init__(
        self,
        posts: list[PostOut] | None = None,
        activity: list[ActivityOut] | None = None,
    ):
        self.posts = posts or []
        self.activity = activity or []
        self.calls: list[tuple[str, Any]] = []

    async def list_posts(
        self,
        profile_id,
        *,
        platform=None,
        kinds=None,
        since=None,
        limit=50,
        include_deleted=False,
    ):
        self.calls.append(("list_posts", profile_id))
        rows = [p for p in self.posts if p.profile_id == profile_id]
        if platform is not None:
            rows = [p for p in rows if p.platform == platform]
        if kinds is not None:
            rows = [p for p in rows if p.kind in kinds]
        else:
            rows = [p for p in rows if p.kind in (None, "original")]
        rows = sorted(rows, key=lambda p: p.published_at, reverse=True)
        if since is not None:
            rows = [p for p in rows if p.published_at >= since]
        return rows[:limit]

    async def get_posts(self, post_ids):
        return [p for p in self.posts if p.id in set(post_ids)]

    async def list_activity(self, profile_id, *, kind=None, limit=50):
        self.calls.append(("list_activity", kind))
        rows = [a for a in self.activity if a.profile_id == profile_id]
        if kind:
            rows = [a for a in rows if a.kind == kind]
        return rows[:limit]

    async def get_baseline(self, profile_id):
        return None

    async def save_baseline(self, baseline):
        return None


class FakeListening:
    def __init__(self, alerts: list[AlertOut] | None = None):
        self.alerts = alerts or []
        self.config = ListeningConfig(profile_id=1)
        self.dismissed: list[int] = []

    async def unread_alerts(self, profile_id):
        return [
            a
            for a in self.alerts
            if a.profile_id == profile_id and a.id not in self.dismissed
        ]

    async def dismiss_alert(self, profile_id, alert_id):
        if alert_id in {a.id for a in self.alerts if a.profile_id == profile_id}:
            self.dismissed.append(alert_id)
            return True
        return False

    async def get_listening(self, profile_id):
        return replace(self.config, profile_id=profile_id)

    async def set_listening(self, config):
        self.config = config
        return config


class FakeRequests:
    def __init__(self):
        self.rows: list[tuple[int, str, str | None]] = []

    async def save_user_request(self, profile_id, handle, note):
        prior = any(r[0] == profile_id and r[1] == handle for r in self.rows)
        self.rows.append((profile_id, handle, note))
        return UserRequestOut(
            id=len(self.rows),
            handle=handle,
            note=note,
            already_requested=prior,
            created_at=NOW,
        )

    async def list_user_requests(self, profile_id, *, limit=50):
        return []


class FakeVoice:
    def __init__(self):
        self.answers: list[StyleAnswerIn] = []
        self.current = None
        self.saved: list[VoiceProfileOut] = []
        self.columns: list[tuple[str, str]] = []

    async def current_voice(self, profile_id, platform=None):
        for voice in reversed(self.saved):
            if voice.profile_id == profile_id and voice.platform == platform:
                return voice
        return self.current if platform is None else None

    async def save_voice(
        self,
        profile_id,
        platform,
        payload,
        source,
        example_post_ids,
        *,
        model="",
        prompt_version="",
    ):
        self.columns.append((model, prompt_version))
        version = len(self.saved) + 1
        voice = VoiceProfileOut(
            id=version,
            profile_id=profile_id,
            platform=platform,
            version=version,
            payload=dict(payload),
            source=source,
            example_post_ids=tuple(example_post_ids),
            created_at=NOW,
        )
        self.saved.append(voice)
        return voice

    async def save_style_answers(self, profile_id, answers):
        self.answers.extend(answers)

    async def list_style_answers(self, profile_id):
        return list(self.answers)


class FakeLinks:
    def __init__(self, link: ConnectLink):
        self.link = link
        self.calls: list[tuple[int, str, str | None]] = []

    async def start_connect(self, profile_id, platform, handle=None):
        self.calls.append((profile_id, platform, handle))
        return self.link


class FakeRepurpose:
    def __init__(self, known: set[int] | None = None):
        self.known = known or {7}
        self.actions: list[tuple[int, int, str, str | None]] = []

    async def create_request_with_attempts(self, *a, **k):
        raise NotImplementedError

    async def record_user_action(
        self, profile_id, attempt_id, action, edited_text=None
    ):
        if attempt_id not in self.known:
            raise LookupError(attempt_id)
        self.actions.append((profile_id, attempt_id, action, edited_text))


class FakeChat:
    def __init__(self, history: list[ChatMessageOut] | None = None):
        self.rows: list[tuple[int, ChatMessageIn]] = []
        self._history = history or []

    async def history(self, profile_id, limit):
        return self._history[-limit:]

    async def append(self, profile_id, message):
        self.rows.append((profile_id, message))
        return len(self.rows)


class FakeMcp:
    def __init__(
        self,
        specs: list[McpToolSpec] | None = None,
        result: McpCallResult | None = None,
    ):
        self.specs = specs or []
        self.result = result or McpCallResult(status="ok", payload={"files": []})
        self.calls: list[tuple[int, str, dict]] = []
        self.pending: McpPendingResolution | None = None
        self.fail_list = False

    async def list_tools(self, profile_id):
        if self.fail_list:
            raise RuntimeError("connector down")
        return list(self.specs)

    async def call(self, profile_id, name, args):
        self.calls.append((profile_id, name, dict(args)))
        return self.result

    async def resolve_pending(self, profile_id, user_message):
        return self.pending


class FakeMemory:
    """Notes plus a rolling summary, in memory."""

    def __init__(self) -> None:
        self.notes: dict[int, MemoryNoteOut] = {}
        self.summary: dict[int, str] = {}
        self.touched: list[int] = []
        self.last_access: dict[int, datetime] = {}

    async def add_note(self, profile_id, text, kind="fact"):
        for note in self.notes.values():
            if note.profile_id == profile_id and note.text == text:
                return note, False
        note = MemoryNoteOut(len(self.notes) + 1, profile_id, text, kind, NOW)
        self.notes[note.id] = note
        self.last_access[note.id] = NOW
        return note, True

    async def get_notes(self, ids):
        return [self.notes[i] for i in ids if i in self.notes]

    async def touch_notes(self, ids):
        self.touched.extend(ids)

    async def list_notes(self, profile_id, *, limit=100):
        rows = [n for n in self.notes.values() if n.profile_id == profile_id]
        return rows[-limit:][::-1]

    async def delete_notes_older_than(self, profile_id, cutoff):
        gone = [
            i
            for i, n in self.notes.items()
            if n.profile_id == profile_id and self.last_access[i] < cutoff
        ]
        for i in gone:
            del self.notes[i]
        return gone

    async def get_summary(self, profile_id):
        return self.summary.get(profile_id, "")

    async def set_summary(self, profile_id, text):
        self.summary[profile_id] = text


def make_peer(
    pid: int,
    text: str,
    *,
    profile_id: int = 1,
    platform: str = "x",
    niche_key: str | None = "ai:global",
) -> PeerPostOut:
    return PeerPostOut(
        id=pid,
        profile_id=profile_id,
        platform=platform,  # type: ignore[arg-type]
        external_id=f"peer{pid}",
        author_handle="rival",
        text=text,
        published_at=NOW,
        url=None,
        metrics=PostMetrics(),
        media=(),
        niche_key=niche_key,
    )


class FakePeers:
    def __init__(self, rows: list[PeerPostOut] | None = None) -> None:
        self.rows = rows or []

    async def save_peer_posts(self, profile_id, posts):
        raise NotImplementedError

    async def get_peer_posts(self, ids):
        return [r for r in self.rows if r.id in set(ids)]

    async def list_peer_posts(self, profile_id, *, niche_key=None, limit=200):
        rows = [r for r in self.rows if r.profile_id == profile_id]
        if niche_key:
            rows = [r for r in rows if r.niche_key == niche_key]
        return rows[:limit]
