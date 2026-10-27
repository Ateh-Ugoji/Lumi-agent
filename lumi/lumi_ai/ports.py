"""Ports of ``lumi_ai``: every boundary between the AI package and the outside world.

Contract version: ``PORTS_VERSION`` (bump the minor number for additive changes, the
major number for anything that breaks an implementer).

Who implements what
-------------------
* LUMI-CONNECT implements :class:`SocialData` (``apps/connections/socialdata.py``),
  :class:`McpGateway` (``apps/connections/mcp/gateway.py``) and
  :class:`ConnectionLinks` (``apps/connections/connect_links.py``).
* LUMI-INTELLIGENCE implements the stores below on top of the Django ORM
  (``apps/intelligence/repos.py``), going through ``apps.profiles.services`` and
  ``apps.chat.services`` (LUMI-ARCHITECT) for the tables they own.
* LUMI-INTELLIGENCE implements :class:`Embedder`, :class:`VectorStore`,
  :class:`VideoAnalyzer` and the key probes inside ``lumi_ai`` itself.

Conventions
-----------
* Every store and gateway method is ``async``. :class:`Embedder`, :class:`VectorStore`
  and :class:`Clock` are synchronous (CPU or blocking client); async callers wrap them
  with ``asyncio.to_thread``.
* Data crosses a port as a frozen dataclass or a JSON-compatible ``dict``. Never an ORM
  instance.
* ``None`` means "unknown". A missing metric is ``None``, never ``0``: zeros drag
  medians, baselines and outlier tests (see ``docs/profile_extract_audit.md``).
* Datetimes are timezone-aware (UTC).
* ``profile_id`` is the primary key of the Lumi profile (``SocialProfile`` in
  ``docs/SCHEMA.md``) that every user-owned row hangs from. Stores must refuse access to a
  profile the current request does not own; the AI package never checks permissions.
* Vector ids have the form ``<type>:<postgres_id>`` (``post:812``). The vector store
  holds vectors and filter metadata only, never text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, get_args, runtime_checkable

PORTS_VERSION = "1.11"  # 1.1: SemanticJudge, 1.2: OwnPostSync, 1.3: AttemptIn.is_fallback, EvaluationRecord.attempt_id required, 1.4: MemoryStore.touch_notes, save_voice model/prompt_version, 1.5: tool_call_id, report query/peers, repurpose mode/brief, user request platform, 1.6: MatchStore, 1.7: create_request_with_attempts(source_post_id=), 1.8: create_request_with_attempts(evaluations=) + EvaluationIn, 1.9: MediaRef.kind may be None (type unknown), 1.10: VideoAnalysisStore, 1.11: author_avatar_url on PostIn/PeerPostIn/PeerPostOut

# ---------------------------------------------------------------------------
# Shared vocabulary
# ---------------------------------------------------------------------------

Platform = Literal["x", "linkedin", "facebook", "tiktok", "instagram"]
PLATFORMS: tuple[str, ...] = get_args(Platform)

PostKind = Literal["original", "reply", "retweet", "quote"]
MediaKind = Literal["image", "video", "gif"]
ChatRole = Literal["user", "assistant", "tool"]
Tier = Literal["small", "large"]
ToolCost = Literal["free", "credits", "llm", "write"]


@dataclass(frozen=True, slots=True)
class MediaRef:
    """One media attachment of a post.

    ``kind`` is ``None`` (1.9) when the source gives only a URL and no type, as X's ``mediaUrls``
    do. ``None`` means "unknown", never "image": a consumer that needs the type decides from the
    URL itself and skips what it cannot tell.
    """

    kind: MediaKind | None
    url: str


@dataclass(frozen=True, slots=True)
class PostMetrics:
    """Engagement counters. Each field is ``None`` when the source did not report it."""

    views: int | None = None
    likes: int | None = None
    comments: int | None = None  # replies / comments
    shares: int | None = None  # reposts / retweets / shares
    bookmarks: int | None = None
    quotes: int | None = None


@dataclass(frozen=True, slots=True)
class PostIn:
    """A post as a source (Post for Me, Xpoz, ...) reports it, before it has a database id.

    ``SocialData`` returns these; ingestion hands them to ``apps.profiles.services``.
    """

    platform: Platform
    external_id: str  # the platform's own post id
    text: str
    published_at: datetime
    author_handle: str | None = None  # without "@", lowercase
    kind: PostKind | None = None  # None = could not classify
    url: str | None = None
    metrics: PostMetrics = field(default_factory=PostMetrics)
    media: tuple[MediaRef, ...] = ()
    conversation_id: str | None = None
    language: str | None = None
    source: str | None = None  # "pfm" | "xpoz" | ...
    text_truncated: bool = False
    # The author's photo when the source reports it with the post. None = the source does not
    # (Xpoz post rows carry no avatar; only its user endpoints do). Never guessed or built.
    author_avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class PostOut:
    """A stored post. ``id`` is the Postgres id used in vector ids (``post:<id>``)."""

    id: int
    profile_id: int
    platform: Platform
    external_id: str
    text: str
    published_at: datetime
    kind: PostKind | None = None
    url: str | None = None
    author_handle: str | None = None
    metrics: PostMetrics | None = None  # latest snapshot; None = no snapshot yet
    metrics_age_hours: float | None = None
    media: tuple[MediaRef, ...] = ()
    is_deleted_suspect: bool = False
    text_truncated: bool = False


@dataclass(frozen=True, slots=True)
class ActivityOut:
    """A reply or retweet by the user. Replies are voice material; retweets never are."""

    id: int
    profile_id: int
    platform: Platform
    kind: Literal["reply", "retweet"]
    text: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class UserInfo:
    """A public account on a social platform."""

    platform: Platform
    handle: str
    external_id: str | None = None
    display_name: str | None = None
    bio: str | None = None
    followers: int | None = None
    following: int | None = None
    verified: bool | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileInfo:
    """What the agent needs to know about a profile. Built from ``SocialProfile``."""

    id: int
    name: str
    handle: str
    primary_platform: Platform
    connected_platforms: tuple[Platform, ...] = ()
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class BaselineOut:
    """Own-account baseline over recent originals (median/p75 of views and engagement)."""

    profile_id: int
    window_days: int
    n_posts: int
    median_views: float
    median_engagement: float
    p75_views: float
    reliable: bool
    computed_at: datetime


# ---------------------------------------------------------------------------
# Errors raised by SocialData (and understood by the AI package)
# ---------------------------------------------------------------------------


class SocialDataError(Exception):
    """Base class of every error a :class:`SocialData` implementation may raise."""

    def __init__(self, message: str = "", *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class BudgetExceeded(SocialDataError):
    """The per-run credit budget (``XPOZ_RUN_CREDIT_BUDGET``) is spent."""

    def __init__(
        self,
        message: str = "",
        *,
        provider: str | None = None,
        spent: int | None = None,
        budget: int | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.spent = spent
        self.budget = budget


class ProviderUnavailable(SocialDataError):
    """The provider is down, timed out, or has no key configured."""


class RateLimited(SocialDataError):
    """The provider answered 429 or the local limiter refused the call."""

    def __init__(
        self,
        message: str = "",
        *,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after_seconds = retry_after_seconds


class ProviderAuthError(SocialDataError):
    """The credential was rejected (401/403): expired token, wrong key, missing scope."""


class LiveDisabled(SocialDataError):
    """Live calls are switched off by configuration (for example ``X_LIVE_ENABLED=false``)."""


class UnsupportedPlatform(SocialDataError):
    """The platform has no way to read this data (for example LinkedIn posts of third parties)."""


# ---------------------------------------------------------------------------
# Social data (implemented by LUMI-CONNECT)
# ---------------------------------------------------------------------------


@runtime_checkable
class SocialData(Protocol):
    """Read access to public social data. The AI package never calls a provider directly.

    Implementations enforce credit budgets, rotate keys and raise the typed errors above.
    ``UnsupportedPlatform`` is the honest answer when a platform offers no API for the call.
    """

    async def fetch_user_posts(
        self, platform: Platform, handle: str, since: datetime | None, limit: int
    ) -> list[PostIn]:
        """Return up to ``limit`` recent posts of ``handle`` published after ``since``, newest first."""
        ...

    async def search_posts(
        self, platform: Platform, query: str, limit: int
    ) -> list[PostIn]:
        """Return up to ``limit`` public posts that match a keyword query."""
        ...

    async def get_user(self, platform: Platform, handle: str) -> UserInfo | None:
        """Return the public account for ``handle``, or ``None`` when it does not exist."""
        ...

    async def search_users(
        self, platform: Platform, query: str, limit: int
    ) -> list[UserInfo]:
        """Return up to ``limit`` public accounts that match a query."""
        ...


# ---------------------------------------------------------------------------
# MCP and account connection (implemented by LUMI-CONNECT)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    """A tool offered by an MCP connector, in the shape the agent loop emits to the model."""

    name: str  # namespaced, for example "mcp__gdocs__create_document"
    description: str
    parameters: Mapping[str, Any]  # JSON schema
    cost: ToolCost = "free"
    requires_confirmation: bool = False  # write tools stop at the confirmation gate


@dataclass(frozen=True, slots=True)
class McpCallResult:
    """Outcome of one MCP call.

    ``status="confirmation_required"`` means a write was parked, not run. The pending write
    must live in the database, not in process memory (it must survive several workers).
    """

    status: Literal["ok", "confirmation_required", "error"]
    payload: Mapping[str, Any] = field(default_factory=dict)
    summary: str | None = None  # human-readable description of a parked write
    error: str | None = None


@dataclass(frozen=True, slots=True)
class McpPendingResolution:
    """What happened to a parked write once the user answered."""

    note: str  # model-facing note with the real outcome
    tool: str | None = None  # set only when a tool actually ran
    arguments: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] | None = None


@runtime_checkable
class McpGateway(Protocol):
    """MCP connectors (Google Drive, Google Docs, ...) scoped to one profile."""

    async def list_tools(self, profile_id: int) -> list[McpToolSpec]:
        """Return the tools this profile can use (empty when no connector is connected)."""
        ...

    async def call(
        self, profile_id: int, name: str, args: Mapping[str, Any]
    ) -> McpCallResult:
        """Run a read tool now, or park a write tool until the user confirms."""
        ...

    async def resolve_pending(
        self, profile_id: int, user_message: str
    ) -> McpPendingResolution | None:
        """Run the parked write on a clear yes, cancel it otherwise; ``None`` if nothing is parked."""
        ...


@dataclass(frozen=True, slots=True)
class ConnectLink:
    """Result of asking to connect a social account."""

    already_connected: bool
    url: str | None = None  # where the user must go; None when already connected
    handle: str | None = None
    message: str | None = None


@runtime_checkable
class ConnectionLinks(Protocol):
    """Starts the OAuth flow of a social account. The agent only mints the link."""

    async def start_connect(
        self, profile_id: int, platform: Platform, handle: str | None = None
    ) -> ConnectLink:
        """Return the URL for the user to connect ``platform``, or say it is already connected."""
        ...


# ---------------------------------------------------------------------------
# Stores (implemented over the Django ORM by LUMI-INTELLIGENCE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NicheIn:
    """The niche a profile writes about. ``niche_key`` is ``<slug>:<geo_scope>``."""

    niche_key: str
    title: str
    keywords: tuple[str, ...] = ()
    tracked_handles: Mapping[Platform, tuple[str, ...]] = field(default_factory=dict)
    source: Literal["user", "inferred"] = "user"


@dataclass(frozen=True, slots=True)
class NicheOut:
    profile_id: int
    niche_key: str
    title: str
    keywords: tuple[str, ...]
    tracked_handles: Mapping[Platform, tuple[str, ...]]
    source: Literal["user", "inferred"]
    updated_at: datetime


@runtime_checkable
class ProfileStore(Protocol):
    """Profile identity and niche preference."""

    async def get_profile(self, profile_id: int) -> ProfileInfo | None:
        """Return the profile, or ``None`` when it does not exist or is not accessible."""
        ...

    async def get_niche(self, profile_id: int) -> NicheOut | None:
        """Return the profile's niche preference, or ``None`` when never set."""
        ...

    async def save_niche(self, profile_id: int, niche: NicheIn) -> NicheOut:
        """Create or replace the niche preference."""
        ...


@runtime_checkable
class PostStore(Protocol):
    """The profile's own posts, replies and baseline."""

    async def list_posts(
        self,
        profile_id: int,
        *,
        platform: Platform | None = None,
        kinds: Sequence[PostKind] | None = None,
        since: datetime | None = None,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> list[PostOut]:
        """Return posts newest first; ``kinds=None`` means originals only."""
        ...

    async def get_posts(self, post_ids: Sequence[int]) -> list[PostOut]:
        """Return the posts with these ids (the texts behind ``post:<id>`` vectors)."""
        ...

    async def list_activity(
        self,
        profile_id: int,
        *,
        kind: Literal["reply", "retweet"] | None = None,
        limit: int = 50,
    ) -> list[ActivityOut]:
        """Return the user's replies and retweets, newest first."""
        ...

    async def get_baseline(self, profile_id: int) -> BaselineOut | None:
        """Return the latest stored baseline, or ``None``."""
        ...

    async def save_baseline(self, baseline: BaselineOut) -> None:
        """Append a recomputed baseline (latest row wins)."""
        ...


@dataclass(frozen=True, slots=True)
class PeerPostIn:
    """A post of somebody else (a competitor), kept so its text can be recalled after a vector search."""

    platform: Platform
    external_id: str
    author_handle: str
    text: str
    published_at: datetime | None = None
    url: str | None = None
    metrics: PostMetrics = field(default_factory=PostMetrics)
    media: tuple[MediaRef, ...] = ()
    niche_key: str | None = None
    author_avatar_url: str | None = (
        None  # from the source; the store fills the handle only if empty
    )


@dataclass(frozen=True, slots=True)
class PeerPostOut:
    id: int
    profile_id: int
    platform: Platform
    external_id: str
    author_handle: str
    text: str
    published_at: datetime | None
    url: str | None
    metrics: PostMetrics
    media: tuple[MediaRef, ...]
    niche_key: str | None
    author_avatar_url: str = ""  # the stored handle's photo, "" when nobody has one


@runtime_checkable
class PeerPostStore(Protocol):
    """Third-party posts the analysis looked at. Postgres owns the text; Chroma holds ``peer_post:<id>``."""

    async def save_peer_posts(
        self, profile_id: int, posts: Sequence[PeerPostIn]
    ) -> list[PeerPostOut]:
        """Insert or update by (profile, platform, external id) and return the stored rows."""
        ...

    async def get_peer_posts(self, ids: Sequence[int]) -> list[PeerPostOut]:
        """Return the peer posts with these ids."""
        ...

    async def list_peer_posts(
        self, profile_id: int, *, niche_key: str | None = None, limit: int = 200
    ) -> list[PeerPostOut]:
        """Return stored peer posts, newest first."""
        ...


@dataclass(frozen=True, slots=True)
class VoiceProfileOut:
    """A learned writing style. ``payload`` follows ``lumi_ai.style.schema.VoicePayload``."""

    id: int
    profile_id: int
    platform: Platform | None  # None = general voice
    version: int
    payload: Mapping[str, Any]
    source: Literal["posts", "questions"]
    example_post_ids: tuple[int, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StyleAnswerIn:
    question_key: str
    answer: str


@runtime_checkable
class VoiceStore(Protocol):
    """Voice profiles, their examples and the cold-start questionnaire."""

    async def current_voice(
        self, profile_id: int, platform: Platform | None = None
    ) -> VoiceProfileOut | None:
        """Return the current voice for the platform (``None`` = general voice), or ``None``."""
        ...

    async def save_voice(
        self,
        profile_id: int,
        platform: Platform | None,
        payload: Mapping[str, Any],
        source: Literal["posts", "questions"],
        example_post_ids: Sequence[int],
        *,
        model: str = "",
        prompt_version: str = "",
    ) -> VoiceProfileOut:
        """Store a new version and make it the only current one, in one transaction.

        ``model`` and ``prompt_version`` fill the columns of the same name (1.4).
        """
        ...

    async def save_style_answers(
        self, profile_id: int, answers: Sequence[StyleAnswerIn]
    ) -> None:
        """Insert or replace answers by ``question_key``."""
        ...

    async def list_style_answers(self, profile_id: int) -> list[StyleAnswerIn]:
        """Return the stored answers."""
        ...


@dataclass(frozen=True, slots=True)
class TaggingRecord:
    """One post's blind-tagging result, cached by (post_ref, prompt_version)."""

    post_ref: str  # "<platform>:<external_id>" of the analyzed post
    handle: str
    prompt_version: str
    status: Literal["ok", "failed"]
    analysis: Mapping[str, Any] | None = None  # never invented on failure
    framework_guess: str | None = None
    validation_error: str | None = None


@dataclass(frozen=True, slots=True)
class FrameworkIn:
    """A winning structure found in a niche.

    Storage (``frameworks``): the column ``name`` holds ``title`` ("name es el título"), and
    ``name`` (the stable key, e.g. ``pas``) travels inside ``payload["key"]``; the producer
    always writes it there. ``evidence_post_refs`` are ``"<platform>:<external_id>"`` and become
    ``framework_evidence`` rows, so those posts must already be stored (``PeerPostStore`` first).
    """

    name: str
    title: str
    description: str
    evidence_post_refs: tuple[str, ...] = ()
    lift: float | None = None
    confidence: float | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FrameworkOut:
    id: int
    profile_id: int
    report_id: int
    name: str
    title: str
    description: str
    evidence_post_refs: tuple[str, ...]
    lift: float | None
    confidence: float | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NicheReportIn:
    niche_key: str | None
    status: Literal["ok", "insufficient_data", "failed"]
    posts_analyzed: int
    winner_count: int
    payload: Mapping[str, Any]  # validated model output, kept raw
    frameworks: tuple[FrameworkIn, ...] = ()
    detail: str | None = None  # honest reason when not "ok"
    # 1.5: niche_reports.query / peers_analyzed and niche_report_peers (platform from the key)
    query: str = ""
    peers_analyzed: int = 0
    peer_handles: Mapping[Platform, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NicheReportOut:
    id: int
    profile_id: int
    niche_key: str | None
    status: Literal["ok", "insufficient_data", "failed"]
    posts_analyzed: int
    winner_count: int
    payload: Mapping[str, Any]
    frameworks: tuple[FrameworkOut, ...]
    detail: str | None
    created_at: datetime
    query: str = ""  # 1.5
    peers_analyzed: int = 0  # 1.5


@runtime_checkable
class ReportStore(Protocol):
    """Competitor analysis output: reports, frameworks and the blind-tagging cache."""

    async def save_report(
        self, profile_id: int, report: NicheReportIn
    ) -> NicheReportOut:
        """Store a report and its frameworks atomically."""
        ...

    async def latest_report(self, profile_id: int) -> NicheReportOut | None:
        """Return the newest report, whatever its status."""
        ...

    async def get_frameworks(self, ids: Sequence[int]) -> list[FrameworkOut]:
        """Return the frameworks with these ids (the texts behind ``framework:<id>`` vectors)."""
        ...

    async def list_frameworks(
        self, profile_id: int, *, limit: int = 100
    ) -> list[FrameworkOut]:
        """Return the profile's frameworks, newest first."""
        ...

    async def save_taggings(
        self, profile_id: int, taggings: Sequence[TaggingRecord]
    ) -> int:
        """Upsert by (post_ref, prompt_version) and return how many rows changed."""
        ...

    async def cached_taggings(
        self, profile_id: int, post_refs: Sequence[str], prompt_version: str
    ) -> list[TaggingRecord]:
        """Return stored taggings for these posts under this prompt version."""
        ...


@dataclass(frozen=True, slots=True)
class MemoryNoteOut:
    id: int
    profile_id: int
    text: str
    kind: str
    created_at: datetime


@runtime_checkable
class MemoryStore(Protocol):
    """Durable facts about the user and a rolling summary. Replaces ``memory.md``."""

    async def add_note(
        self, profile_id: int, text: str, kind: str = "fact"
    ) -> tuple[MemoryNoteOut, bool]:
        """Store a note; return ``(note, created)``. An exact duplicate returns the old note and ``False``."""
        ...

    async def get_notes(self, ids: Sequence[int]) -> list[MemoryNoteOut]:
        """Return the notes with these ids (the texts behind ``memory:<id>`` vectors)."""
        ...

    async def touch_notes(self, ids: Sequence[int]) -> None:
        """Record a recall: bump ``access_count`` and ``last_accessed_at`` so decay spares used notes (1.4)."""
        ...

    async def list_notes(
        self, profile_id: int, *, limit: int = 100
    ) -> list[MemoryNoteOut]:
        """Return the newest notes."""
        ...

    async def delete_notes_older_than(
        self, profile_id: int, cutoff: datetime
    ) -> list[int]:
        """Delete decayed notes and return their ids so the caller can drop their vectors."""
        ...

    async def get_summary(self, profile_id: int) -> str:
        """Return the rolling summary, or an empty string."""
        ...

    async def set_summary(self, profile_id: int, text: str) -> None:
        """Replace the rolling summary."""
        ...


@dataclass(frozen=True, slots=True)
class ChatMessageIn:
    role: ChatRole
    content: str
    tool_calls: Sequence[Mapping[str, Any]] | None = None
    tool_name: str | None = None
    tools_used: Sequence[str] | None = None
    reason: str | None = None  # the `reason` argument the model gave for a tool call
    tool_call_id: str | None = None  # 1.5: id of the call a "tool" row answers


@dataclass(frozen=True, slots=True)
class ChatMessageOut:
    id: int
    profile_id: int
    role: ChatRole
    content: str
    created_at: datetime
    tool_calls: tuple[Mapping[str, Any], ...] | None = None
    tool_name: str | None = None
    tools_used: tuple[str, ...] | None = None
    reason: str | None = None
    tool_call_id: str | None = None  # 1.5


@runtime_checkable
class ChatStore(Protocol):
    """Conversation history. Implemented on ``apps.chat.services`` (LUMI-ARCHITECT)."""

    async def history(self, profile_id: int, limit: int) -> list[ChatMessageOut]:
        """Return the last ``limit`` messages, oldest first, tool rows included."""
        ...

    async def append(self, profile_id: int, message: ChatMessageIn) -> int:
        """Store a message and return its id."""
        ...


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One classified agent turn, for audit and the ``/health`` metrics."""

    profile_id: int
    message_id: int | None
    message_text_hash: str
    message_preview: str
    rule_class: str
    rule_matched: str | None
    final_class: str
    path_taken: Literal["fast", "full"]
    tools_called: tuple[str, ...] = ()
    judge_called: bool = False
    judge_class: str | None = None
    judge_probs: tuple[Mapping[str, Any], ...] | None = None
    judge_confidence: float | None = None
    judge_latency_ms: int | None = None
    judge_error: str | None = None
    total_latency_ms: int | None = None
    timings: Mapping[str, Any] | None = None  # unknown keys stay absent, never 0


@runtime_checkable
class TurnLogStore(Protocol):
    """Audit trail of turns. A failed write must never break the turn."""

    async def record_turn(self, record: TurnRecord) -> int:
        """Store the record and return its id."""
        ...

    async def mark_corrected(self, record_id: int) -> None:
        """Flag a turn the user later corrected (a misroute)."""
        ...


@dataclass(frozen=True, slots=True)
class AttemptIn:
    platform: Platform
    output: str
    attempt_no: int
    must_keep_passed: bool
    tier: Tier | None = None
    model: str | None = None
    provider: str | None = None
    judge_verdict: Literal["yes", "no"] | None = None
    judge_confidence: float | None = None
    is_fallback: bool = (
        False  # 1.3: the model chain fell back to a lower tier for this attempt
    )


@dataclass(frozen=True, slots=True)
class AttemptOut:
    id: int
    request_id: int
    platform: Platform
    output: str
    attempt_no: int
    must_keep_passed: bool
    judge_verdict: str | None
    judge_confidence: float | None
    created_at: datetime


@runtime_checkable
class RepurposeStore(Protocol):
    """Rewrite requests, their attempts and what the user did with them."""

    async def create_request_with_attempts(
        self,
        profile_id: int,
        source_text: str,
        route_label: str | None,
        attempts: Sequence[AttemptIn],
        *,
        mode: Literal["repurpose", "topic"] = "repurpose",
        brief: str | None = None,
        source_post_id: int | None = None,
        evaluations: Mapping[int, EvaluationIn] | None = None,
    ) -> tuple[int, list[AttemptOut]]:
        """Store a request, its attempts and their evaluations in ONE transaction.

        Returns ``(request_id, attempts)``.

        ``source_post_id`` links the stored post a repurpose started from (1.7); it must belong
        to ``profile_id``.

        ``evaluations`` (1.8) are the already computed evaluations keyed by ``attempt_no``. The
        ids of the attempts only exist after the insert, so the store writes the evaluations
        inside the same transaction with the ids it just got. A key with no matching attempt is
        a ``ValueError`` and nothing is stored. An evaluation that cannot be stored fails the
        whole call: there are no attempts without their evaluation.

        The old code saved the request before doing the work, so a failure left orphans.
        """
        ...

    async def record_user_action(
        self,
        profile_id: int,
        attempt_id: int,
        action: Literal["accept", "edit", "reject"],
        edited_text: str | None = None,
    ) -> None:
        """Record the user's decision on an attempt (the agent never publishes by itself).

        Raises ``LookupError`` when the attempt does not exist or belongs to another profile.
        """
        ...


@dataclass(frozen=True, slots=True)
class UserRequestOut:
    id: int
    handle: str  # normalized: no "@", lowercase
    note: str | None
    already_requested: bool
    created_at: datetime


@runtime_checkable
class RequestStore(Protocol):
    """Accounts the user explicitly asked Lumi to look up. Never merged into peer data."""

    async def save_user_request(
        self,
        profile_id: int,
        handle: str,
        note: str | None,
        *,
        platform: Platform | None = None,
    ) -> UserRequestOut:
        """Append a request (re-requests add rows; ``already_requested`` is computed on read)."""
        ...

    async def list_user_requests(
        self, profile_id: int, *, limit: int = 50
    ) -> list[UserRequestOut]:
        """Return the newest requests."""
        ...


@dataclass(frozen=True, slots=True)
class AlertOut:
    id: int
    profile_id: int
    post_id: int
    kind: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ListeningConfig:
    profile_id: int
    keywords: tuple[str, ...] = ()
    enabled: bool = False
    interval_minutes: int | None = None


@runtime_checkable
class ListeningStore(Protocol):
    """Alerts and the social-listening configuration (``apps.profiles.services`` owns the rows)."""

    async def unread_alerts(self, profile_id: int) -> list[AlertOut]:
        """Return alerts not yet dismissed."""
        ...

    async def dismiss_alert(self, profile_id: int, alert_id: int) -> bool:
        """Dismiss an alert; return ``False`` when it does not exist."""
        ...

    async def get_listening(self, profile_id: int) -> ListeningConfig:
        """Return the listening config (disabled by default)."""
        ...

    async def set_listening(self, config: ListeningConfig) -> ListeningConfig:
        """Replace the listening config."""
        ...


@runtime_checkable
class MatchStore(Protocol):
    """Posts of other accounts a profile found while listening to its niche (``listening_matches``).

    1.6. The row is a bridge ``(profile, post)``: the post itself (text, author, url, metrics) is
    stored first through :class:`PeerPostStore`. Reading matches is the API's job, not the AI's.
    """

    async def record_listening_match(
        self, profile_id: int, post_id: int, score: float | None = None
    ) -> bool:
        """Link a stored post to the profile; ``False`` when the link already existed."""
        ...


@dataclass(frozen=True, slots=True)
class EvaluationIn:
    """Automatic quality evaluation of one generated draft, before it has an attempt id (1.8)."""

    profile_id: int
    platform: Platform
    draft: str
    decision: Literal["pass", "regenerate", "fail"]
    scores: Mapping[str, float]  # criterion -> 0..1
    reasons: Mapping[str, str]  # criterion -> one-line reason
    deterministic_failures: tuple[str, ...] = ()
    style_similarity: float | None = None
    judge: str | None = None  # "jev" | "groq-small" | "rules"
    config_version: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationRecord(EvaluationIn):
    """A stored evaluation.

    1.3: ``attempt_id`` is required (the schema's ``generation_evaluations.attempt_id`` is a
    non-null FK). It is keyword-only, so the position of every other argument is unchanged.
    """

    attempt_id: int = field(kw_only=True)


@runtime_checkable
class EvalStore(Protocol):
    """Persistence for :class:`EvaluationRecord`."""

    async def save_evaluation(self, record: EvaluationRecord) -> int:
        """Store an evaluation and return its id."""
        ...

    async def list_evaluations(
        self, profile_id: int, *, limit: int = 50
    ) -> list[EvaluationRecord]:
        """Return the newest evaluations."""
        ...


# ---------------------------------------------------------------------------
# Vectors (implemented inside lumi_ai)
# ---------------------------------------------------------------------------

Vector = Sequence[float]
VectorFilter = Mapping[str, str | int | bool]


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. Blocking; wrap with ``asyncio.to_thread`` in async code."""

    @property
    def name(self) -> str:
        """Stable identifier of the model; stored so a change forces a reindex."""
        ...

    @property
    def dimension(self) -> int:
        """Length of every vector this embedder returns."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in order."""
        ...


@dataclass(frozen=True, slots=True)
class VectorHit:
    """One search result: the id and the distance. The text comes from Postgres by id."""

    id: str  # "<type>:<postgres_id>"
    distance: float
    metadata: Mapping[str, str | int | bool] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """Vectors plus minimal filter metadata. It must never receive ``documents``."""

    def upsert(
        self,
        collection: str,
        ids: Sequence[str],
        embeddings: Sequence[Vector],
        metadatas: Sequence[VectorFilter],
    ) -> None:
        """Insert or replace vectors. Metadata is limited to ``profile_id``, ``platform``, ``kind``, ``niche_key``."""
        ...

    def query(
        self,
        collection: str,
        embedding: Vector,
        k: int,
        where: VectorFilter | None = None,
    ) -> list[VectorHit]:
        """Return the ``k`` nearest ids, closest first."""
        ...

    def delete(self, collection: str, ids: Sequence[str]) -> None:
        """Remove vectors by id (missing ids are ignored)."""
        ...

    def reset(self, collection: str) -> None:
        """Drop every vector of a collection (used by ``reindex_vectors``)."""
        ...


# ---------------------------------------------------------------------------
# Video (implemented inside lumi_ai; adapter chosen by VIDEO_PROVIDER)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VideoAnalysis:
    """Structured reading of one video. Every field is ``None`` when the model could not tell."""

    media_url: str
    provider: str
    prompt_version: str
    duration_seconds: float | None = None
    hook_first_3s: str | None = None
    transcript: str | None = None
    on_screen_text: tuple[str, ...] = ()
    cut_count: int | None = None
    pace: Literal["slow", "medium", "fast"] | None = None
    has_captions: bool | None = None
    call_to_action: str | None = None
    format: str | None = None  # "talking_head", "screen_recording", "montage", ...


class VideoUnavailable(Exception):
    """Video analysis is switched off (no ``VIDEO_PROVIDER``) or the provider refused the call."""


@runtime_checkable
class VideoAnalyzer(Protocol):
    """Analyses a video from a public URL. Never runs without ``VIDEO_PROVIDER`` and its key."""

    async def analyze(
        self, media_url: str, *, context: str | None = None
    ) -> VideoAnalysis:
        """Return the structured analysis; raise :class:`VideoUnavailable` when it cannot run."""
        ...


@runtime_checkable
class VideoAnalysisStore(Protocol):
    """Cache of video analyses in ``video_analysis_records``, keyed by stored media row.

    The key is ``(media row, provider, prompt_version)``. A URL that has no ``post_media`` row yet
    is simply not cached: ``cached`` omits it and ``save_*`` skips it and says so in the count.
    """

    async def cached(
        self, media_urls: Sequence[str], *, provider: str, prompt_version: str
    ) -> dict[str, VideoAnalysis]:
        """Successful analyses already stored, by media URL."""
        ...

    async def save(self, analyses: Sequence[VideoAnalysis], *, model: str) -> int:
        """Store successful analyses; return how many were written (rows without media are skipped)."""
        ...

    async def save_failure(
        self,
        media_url: str,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        error: str,
    ) -> bool:
        """Record why an analysis failed (never replaces a successful one); ``False`` if skipped."""
        ...


# ---------------------------------------------------------------------------
# Own-post synchronisation
# ---------------------------------------------------------------------------


@runtime_checkable
class OwnPostSync(Protocol):
    """Pulls the profile's OWN posts from its connected account into Postgres.

    Implemented by LUMI-CONNECT / LUMI-ARCHITECT on top of the connected-account feed and
    ``apps.profiles.services`` (ingest policy: NULL-preserving metrics, kind routing). The agent
    tool ``backfill_posts`` only triggers it.
    """

    async def sync_own_posts(
        self, profile_id: int, platform: Platform | None = None
    ) -> dict[str, Any]:
        """Fetch and store the posts; return a JSON summary (``stored``, ``platform``, ...).

        Raises :class:`SocialDataError` subclasses on provider problems.
        """
        ...


# ---------------------------------------------------------------------------
# Semantic judge ("Jev")
# ---------------------------------------------------------------------------


@runtime_checkable
class SemanticJudge(Protocol):
    """Answers structured questions about a state; never generates text.

    Both methods are best-effort: ``None`` means "no verdict" (judge unreachable, malformed
    answer, no key) and the caller falls back to its deterministic path. They never raise.
    """

    async def ask_noul(
        self, state: dict[str, Any], questions: dict[str, str]
    ) -> dict[str, float] | None:
        """Score each question 0..1 about ``state``: ``{name: instructions} -> {name: score}``."""
        ...

    async def ask_choice(
        self,
        state: dict[str, Any],
        name: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> str | None:
        """Pick one key of ``criteria`` for ``state``, or ``None``."""
        ...


# ---------------------------------------------------------------------------
# Time and key probes
# ---------------------------------------------------------------------------


@runtime_checkable
class Clock(Protocol):
    """Source of time, replaceable in tests."""

    def now(self) -> datetime:
        """Return the current aware UTC time."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic clock reading in seconds."""
        ...


ProbeStatus = Literal["ok", "skipped", "error"]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of a key probe. Never carries a key value."""

    name: str
    status: ProbeStatus
    detail: str = (
        ""  # "OMITIDA (opcional, falta GROQ_API_KEY)", an exact provider error, ...
    )
    warnings: tuple[str, ...] = ()  # for example "configured model X no longer exists"


@runtime_checkable
class KeyProbe(Protocol):
    """The hook LUMI-ARCHITECT's ``check_keys`` registers (``apps.core.keys.register``).

    ``run`` makes one minimal real call (list models, a one-token completion). It returns
    ``skipped`` when an optional variable is missing, ``error`` with the provider's exact
    message otherwise, and never raises.
    """

    name: str
    required: bool
    env_vars: tuple[str, ...]

    async def run(self) -> ProbeResult:
        """Make the minimal call and report."""
        ...
