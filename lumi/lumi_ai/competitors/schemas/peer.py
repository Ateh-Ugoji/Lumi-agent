"""Pydantic v2 schemas for the competitor (peer) framework analysis.

Ported from ``app/schemas/peer.py``. Differences: ``PostMetrics`` is called ``PostStats`` (it
clashed with ``ports.PostMetrics``), and a counter that was not reported is ``None``, never 0.

Provenance rule (body_structure_knowledge.md section 8):
  scraped      = straight from the Xpoz API
  computed     = deterministic, calculated in code (NEVER ask the LLM for these)
  llm_inferred = judgment calls, produced by the post-analysis prompt

Only the models under "LLM OUTPUT" are produced by the LLM.
Everything under "SCRAPED / COMPUTED" is filled by code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
class PeerConfig:
    SCAN_POSTS_PER_ACCOUNT = 60  # fetch this many recent posts per tracked handle
    MIN_ACCOUNT_SAMPLE = 30  # below this, baseline_reliable = False
    MIN_POST_AGE_HOURS = 24  # younger posts haven't matured, exclude
    LOOKBACK_DAYS = 28  # recent 4 weeks only — shared with the own-post
    # baseline (same window both sides, by construction)
    TOP_N_WINNERS = 20
    MAX_WINNERS_PER_ACCOUNT = 5  # stops one account dominating the niche
    # No fixed absolute views bar: the only bar is MIN_OUTLIER_FOR_WINNER
    # relative to the account's own median (a fixed 500 floor judged small
    # accounts by a big account's number). A floor of 0.5x median would be
    # mathematically dead — it can never exclude a post the 1.5x test passed.
    MIN_OUTLIER_FOR_WINNER = 1.5  # must beat the account's own median by 1.5x
    MIN_N_FOR_LIFT = 3  # patterns with fewer posts -> insufficient_data
    LOW_CONFIDENCE = 0.6  # framework confidence under this -> "other"
    BATCH_SIZE = (
        6  # posts per LLM call; legacy 8, lowered for the Groq ~7000-token wall
    )
    # AUDIT FIX: Prompt 1's hard floor — fewer winners means status=insufficient_data,
    # thresholds are never lowered to fill the quota.
    MIN_WINNERS_FOR_REPORT = 8


# --------------------------------------------------------------------------
# ENUMS
# --------------------------------------------------------------------------
PostFormat = Literal[
    "single", "multi_image", "video", "thread", "quote_post", "long_form"
]

HookType = Literal[
    "curiosity_gap",
    "contrarian",
    "stat_shock",
    "pain_callout",
    "result_claim",
    "story_open",
    "confession",
    "list_promise",
    "how_to_promise",
    "command",
    "question",
    "observation",
    "announcement",
    "other",
]
HookModality = Literal[
    "text_only", "text_plus_image", "text_plus_video", "media_carries_hook"
]

Framework = Literal[
    "pas",
    "aida",
    "story_arc",
    "listicle",
    "myth_bust",
    "hot_take",
    "tutorial",
    "bab",
    "build_in_public",
    "observation",
    "other",
]
PainType = Literal[
    "time", "money", "status", "fomo", "frustration", "confusion", "overwhelm"
]
AgitationDevice = Literal[
    "time_cost",
    "money_cost",
    "status_cost",
    "compounding_cost",
    "emotional_cost",
    "competitor_contrast",
]
SolutionType = Literal["tool", "method", "mindset_shift", "resource", "service"]
ProofType = Literal[
    "none", "number", "screenshot", "case_study", "authority", "social_proof"
]
ArcShape = Literal["fall_rise", "rise", "fall", "rise_fall_rise"]
StoryHookStrategy = Literal["outcome_first", "in_medias_res", "confession", "contrast"]
TurningPointType = Literal["decision", "event", "insight", "external_help"]
StakesType = Literal["money", "reputation", "time", "relationship", "survival"]

AIDAAttentionDevice = Literal["stat", "claim", "result", "question", "story_fragment"]

CTAType = Literal[
    "like_bookmark", "repost", "reply_keyword", "follow", "dm", "link", "none"
]
CTAPlacement = Literal["last_line", "first_reply", "bio", "none"]
Friction = Literal["low", "medium", "high"]

POV = Literal["first_person", "first_person_plural", "second_person", "third_person"]
Intent = Literal["educate", "entertain", "inspire", "sell", "community", "announce"]
FunnelStage = Literal["awareness", "consideration", "conversion"]
LineBreakStyle = Literal["one_liners", "short_paragraphs", "dense_block"]

FailureFlag = Literal[
    # hooks
    "clickbait",
    "payoff_missing",
    # PAS
    "generic_problem",
    "over_agitation",
    "pitch_without_mechanism",
    "agitate_longer_than_solve",
    "fake_pain",
    # AIDA
    "attention_without_interest",
    "desire_without_proof",
    "no_action",
    "multi_cta",
    "cta_before_desire",
    # story
    "lesson_without_story",
    "no_stakes",
    "no_turn",
    "humblebrag",
    "too_many_beats",
    "fake_story",
]


# --------------------------------------------------------------------------
# SCRAPED / COMPUTED (filled by code, never by the LLM)
# --------------------------------------------------------------------------
class AccountBaseline(BaseModel):
    handle: str
    followers: int | None = None
    posts_scanned: int
    median_views: float
    median_engagement: float
    p75_views: float
    posts_per_week: float | None = None
    baseline_reliable: bool  # posts_scanned >= PeerConfig.MIN_ACCOUNT_SAMPLE
    # LLM-inferred, optional, filled in a separate light pass
    niche: str | None = None
    sub_niche: str | None = None
    monetization_funnel: str | None = None


class PostStats(BaseModel):
    post_id: str
    handle: str
    url: str | None = None
    created_at: datetime
    age_hours: float
    text: str
    thread_texts: list[str] = Field(default_factory=list)  # tweets 2..n if thread
    format: PostFormat

    # scraped. ``views`` is required: a post without views cannot be scored at all.
    views: int
    likes: int | None = None
    replies: int | None = None
    reposts: int | None = None
    # AUDIT FIX: Xpoz availability for these two is unverified (quoteCount is
    # missing from the current fields param; bookmarkCount unconfirmed). The
    # pipeline rule is "record None + warning, never default a missing metric
    # to 0". engagement_total sums only the values actually present.
    quotes: int | None = None
    bookmarks: int | None = None

    # computed
    # None = not measurable (counter missing, or a zero denominator); never a fake 0
    engagement_total: int | None = None
    engagement_rate_views: float | None = None
    outlier_views: float | None = None  # views / account median views
    outlier_engagement: float | None = (
        None  # engagement_total / account median engagement
    )
    reply_to_like: float | None = None  # high = conversation
    repost_to_like: float | None = None  # high = broad appeal
    bookmark_to_like: float | None = None  # high = reference value
    char_count: int
    line_count: int
    hook_word_count: int
    hashtag_count: int
    # AUDIT FIX (item 6): emoji counts are computed in code alongside hashtags.
    emoji_count: int = 0
    has_external_link: bool
    thread_length: int | None = None

    # AUDIT FIX (item 8): distribution & timing, all computed in code.
    day_of_week: int = Field(ge=0, le=6, description="0=Monday .. 6=Sunday (UTC)")
    hour_utc: int = Field(ge=0, le=23)
    hours_since_prev: float | None = None  # gap to the author's previous post
    hours_to_next: float | None = None  # gap to the author's next post

    # exclusion flags (any True -> not eligible as a winner)
    is_pinned: bool = False
    is_reply: bool = False
    is_repost: bool = False
    is_boosted_suspect: bool = False  # views far above engagement pattern


# --------------------------------------------------------------------------
# LLM OUTPUT: per-post analysis
# --------------------------------------------------------------------------
class HookAnalysis(BaseModel):
    hook_text: str  # verbatim first line / first sentence
    hook_type: HookType
    hook_type_secondary: HookType | None = None
    modality: HookModality
    has_number: bool
    has_named_entity: bool
    open_loop: bool
    promise: str | None = None  # what the reader is promised
    payoff_delivered: bool | None = None
    standalone_in_thread: bool | None = None  # threads only
    specificity: int = Field(ge=1, le=5)
    tension: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    clickbait_flag: bool = False
    confidence: float = Field(ge=0, le=1)


class Beat(BaseModel):
    label: str  # e.g. "problem", "agitate", "turn", "lesson"
    text: str  # verbatim slice of the post


class PASDetail(BaseModel):
    problem_text: str
    agitate_text: str | None = None
    solution_text: str | None = None
    pain_type: PainType
    agitation_devices: list[AgitationDevice] = Field(default_factory=list)
    agitation_steps: int = Field(ge=0, le=5)
    solution_type: SolutionType | None = None
    mechanism_present: bool
    proof_in_solution: ProofType = "none"
    char_split_p: float = Field(ge=0, le=1)
    char_split_a: float = Field(ge=0, le=1)
    char_split_s: float = Field(ge=0, le=1)


class AIDADetail(BaseModel):
    attention_text: str
    interest_text: str | None = None
    desire_text: str | None = None
    action_text: str | None = None
    attention_device: AIDAAttentionDevice
    interest_devices: list[str] = Field(default_factory=list)
    desire_devices: list[str] = Field(default_factory=list)
    proof_before_ask: bool
    multiple_ctas: bool = False


class StoryDetail(BaseModel):
    arc_shape: ArcShape
    hook_strategy: StoryHookStrategy
    beats_present: list[str]
    emotional_curve: list[int] = Field(description="valence per beat, each -2..+2")
    turning_point_text: str | None = None
    turning_point_type: TurningPointType | None = None
    stakes_type: StakesType | None = None
    specifics_count: int = Field(ge=0)
    lesson_text: str | None = None
    lesson_earned: bool | None = None
    pov: Literal["first_person", "third_person"]


class BodyAnalysis(BaseModel):
    primary_framework: Framework
    secondary_framework: Framework | None = None
    framework_confidence: float = Field(ge=0, le=1)
    beats: list[Beat] = Field(default_factory=list)
    pas: PASDetail | None = None
    aida: AIDADetail | None = None
    story_arc: StoryDetail | None = None
    specificity_score: int = Field(ge=1, le=5)
    proof_type: ProofType = "none"
    open_loops: int = Field(ge=0)
    line_break_style: LineBreakStyle
    failure_flags: list[FailureFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _detail_matches_framework(self) -> BodyAnalysis:
        need = {"pas": self.pas, "aida": self.aida, "story_arc": self.story_arc}
        if self.primary_framework in need and need[self.primary_framework] is None:
            raise ValueError(
                f"primary_framework={self.primary_framework} requires its detail block"
            )
        return self


class CTAAnalysis(BaseModel):
    cta_type: CTAType
    placement: CTAPlacement
    multiple_ctas: bool = False
    friction: Friction
    has_incentive: bool = False  # lead magnet, giveaway, keyword drop
    cta_text: str | None = None


class VoiceAnalysis(BaseModel):
    pov: POV
    tone: list[str] = Field(max_length=3)  # e.g. ["blunt", "dry", "technical"]
    formality: int = Field(ge=1, le=5)
    humor: int = Field(ge=0, le=3)
    signature_phrases: list[str] = Field(default_factory=list, max_length=5)


class StrategyAnalysis(BaseModel):
    content_pillar: str
    angle: str  # the specific take within the pillar
    intent: Intent
    funnel_stage: FunnelStage
    trend_jacking: bool = False
    trend_reference: str | None = None
    audience_emotion: str | None = None
    desire_or_pain: str | None = None


class PostAnalysis(BaseModel):
    post_id: str
    hook: HookAnalysis
    body: BodyAnalysis
    cta: CTAAnalysis
    voice: VoiceAnalysis
    strategy: StrategyAnalysis


class PostAnalysisBatch(BaseModel):
    analyses: list[PostAnalysis]


# --------------------------------------------------------------------------
# PERSISTENCE WRAPPER (code-owned; Prompt 2 stores one row per scanned post)
# --------------------------------------------------------------------------
class PostTagging(BaseModel):
    """One scanned post's persisted tagging record.

    Wraps the optional LLM analysis with pipeline-owned status fields so a
    failed/never-run post is representable without inventing an analysis.
    """

    post_id: str
    handle: str
    status: Literal["pending", "ok", "failed"] = "pending"
    analysis: PostAnalysis | None = None
    # AUDIT FIX (Prompt 2): original framework guess kept when confidence < LOW_CONFIDENCE.
    framework_guess: str | None = None
    validation_error: str | None = None
    prompt_version: str | None = None
    tagged_at: datetime | None = None


# --------------------------------------------------------------------------
# SYNTHESIS (lift table computed in code, narrative written by LLM)
# --------------------------------------------------------------------------
class LiftRow(BaseModel):
    dimension: Literal[
        "primary_framework",
        "hook_type",
        "format",
        "cta_type",
        "funnel_stage",
        "content_pillar",
        "hook_modality",
    ]
    value: str
    n_winners: int
    n_baseline: int
    winner_share: float
    baseline_share: float
    lift: float | None = None  # winner_share / baseline_share
    avg_outlier_views: float | None = None
    status: Literal["reported", "insufficient_data"]


class WinningFramework(BaseModel):
    name: str
    structure: list[str]  # ordered beats, e.g. ["Problem", "Agitate", "Solution"]
    hook_formula: str  # template with [placeholders]
    when_to_use: str
    evidence_post_ids: list[str]
    supporting_lift_rows: list[str]  # "dimension=value" keys present in the lift table
    confidence: float = Field(ge=0, le=1)


class SynthesisOutput(BaseModel):
    winning_frameworks: list[WinningFramework] = Field(max_length=5)
    content_pillars: list[str]
    whitespace: list[str]  # patterns that lift but few peers use
    warnings: list[str] = Field(default_factory=list)


class NicheFrameworkReport(BaseModel):
    niche: str
    generated_at: datetime
    status: Literal["ok", "insufficient_data", "failed"]
    accounts: list[AccountBaseline]
    winner_post_ids: list[str]
    posts_analyzed: int
    lift_table: list[LiftRow]
    synthesis: SynthesisOutput | None = None
    trend_delta: list[LiftRow] | None = None  # vs 90 days ago, when history exists
    warnings: list[str] = Field(default_factory=list)
    xpoz_credits_used: int | None = None
    # NOTE: status "failed" must carry NO fabricated frameworks. No canned fallback.
