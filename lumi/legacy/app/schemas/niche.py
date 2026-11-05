"""Pydantic v2 schemas for Lumi's niche extraction + peer discovery.

Landed from niche_schemas.py with audit fixes against niche_opencode_prompts.md
(schema-upgrade table, pipeline, Prompts 1-3). Changes vs the source file are
marked "AUDIT FIX".

Division of labour (same rule as app/schemas/peer.py):
  scraped / computed  = filled by code. NEVER ask the LLM for these.
  llm_inferred        = produced by the niche-synthesis prompt (NicheLLMOutput only)
                        and the peer-vetting prompt (PeerVettingOutput only).

Core idea: the LLM NAMES things (canonical keywords, niche label, geo hypotheses,
queries). Code COUNTS and WEIGHTS them, and VERIFIES every handle/place/quote the
LLM mentions actually exists in the evidence it was given.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
class NicheConfig:
    # evidence windows
    ORIGINALS_WINDOW = 100
    REPLIES_WINDOW = 50
    RETWEETS_WINDOW = 50
    QUOTES_WINDOW = 25
    COMMENT_POSTS_SAMPLED = 5          # top posts (by views) to pull comments for
    COMMENTS_PER_POST = 20
    MIN_ORIGINALS_FOR_INFERENCE = 20   # below this -> thin_history mode (ask the user)

    # AUDIT FIX: capped LLM input sizes (Prompt 2 synthesize.py) — distinct from
    # the evidence windows above, which are what gets *stored/scanned*.
    SYNTH_ORIGINALS = 40
    SYNTH_REPLIES = 25
    SYNTH_RETWEETS = 20
    SYNTH_QUOTES = 10
    SYNTH_COMMENTS = 40
    BIO_SNIPPET_CHARS = 160            # commenter bio cap on store (post_comments)

    # how much each evidence source counts toward a keyword's weight
    SOURCE_WEIGHTS: ClassVar[dict[str, float]] = {
        "bio": 3.0,                    # self-declared, strongest signal
        "original": 1.0,
        "quote": 0.9,
        "comment_received": 0.5,       # audience language, not theirs
        "reply": 0.6,                  # conversation context
        "retweet": 0.4,                # amplifying is not the same as practising
        "comment_on_peer": 0.3,
    }
    RECENCY_HALF_LIFE_DAYS = 45
    ENGAGEMENT_BOOST_CAP = 2.0         # terms in high-outlier posts count up to 2x

    # outputs
    MAX_KEYWORDS = 40
    MAX_QUERIES = 12
    MAX_QUERY_VALIDATION_SEARCHES = 3  # credits: only dry-run the best few
    MIN_QUERY_USABLE_HITS = 5

    # geo
    MIN_GEO_CONFIDENCE_TO_APPLY = 0.6  # below this, geo is a hint, not a filter
    FREE_TEXT_LOCATION_CONFIDENCE_CAP = 0.5   # a bio location alone never exceeds this

    # peer size bands, as ratio of peer_followers / user_followers
    PEER_BAND = (0.3, 5.0)
    ASPIRATIONAL_BAND = (5.0, 50.0)    # anything above is "giant": reference only
    PEERS_TO_KEEP = 10
    ASPIRATIONAL_TO_KEEP = 5
    GIANTS_TO_KEEP = 3
    INACTIVE_DAYS = 30
    # AUDIT FIX: hard-reject thresholds Prompt 3 references but never named.
    MIN_ORIGINAL_RATIO = 0.3           # below this a candidate is mostly RTs -> reject
    BOT_SCORE_REJECT = 0.7             # bot_score at/above this -> reject
    PEER_CACHE_TTL_HOURS = 12          # discovery results cached per Prompt 3.1
    PEER_COMMENT_MINING = False        # optional peer-comment sampling, OFF by default
    VETTING_POSTS_PER_CANDIDATE = 5    # posts fed to RUNTIME PROMPT D


# --------------------------------------------------------------------------
# ENUMS
# --------------------------------------------------------------------------
KeywordType = Literal[
    "topic",        # what they write about ("cross-posting", "fintech")
    "entity",       # tools, brands, protocols, orgs ("Notion", "Paystack")
    "jargon",       # insider vocabulary / slang ("build in public", "wahala")
    "hashtag",
    "cashtag",
    "pain_phrase",  # what the audience complains about or asks
    "format_term",  # content-format words ("thread", "case study")
    "geo_term",     # places, local institutions, currency, local events
]
EvidenceSource = Literal[
    "bio", "original", "quote", "reply", "retweet",
    "comment_received", "comment_on_peer",
]
GeoScope = Literal["creator", "audience", "niche"]
GeoLevel = Literal["country", "region", "city", "global"]
GeoEvidenceSource = Literal[
    "profile_location", "bio", "text_place_mention", "currency",
    "language_pattern", "posting_hours", "commenter_locations",
    "reply_graph", "user_confirmed",
]
GeoRelevance = Literal["local_first", "regional", "global"]
QueryTier = Literal["core", "geo", "audience_pain", "adjacent"]
PeerTier = Literal["peer", "aspirational", "giant"]
SeedSource = Literal[
    "reply_target", "retweet_target", "quote_target", "mention",
    "commenter", "keyword_search", "manual",
]
NeedsConfirmation = Literal["niche", "location", "audience", "keywords"]
PeerFlag = Literal[
    "bot_like", "engagement_farm", "news_aggregator", "giveaway_account",
    "off_niche", "inactive", "mostly_retweets",
]


# --------------------------------------------------------------------------
# SCRAPED: inputs to niche extraction
# --------------------------------------------------------------------------
class ProfileEnrichment(BaseModel):
    handle: str
    display_name: str | None = None
    bio: str | None = None
    location_raw: str | None = None     # free text, often blank or a joke
    website: str | None = None
    followers: int | None = None
    following: int | None = None
    verified_type: str | None = None
    account_created_at: datetime | None = None
    pinned_post_id: str | None = None
    profile_lang: str | None = None
    fetched_at: datetime


class ReplyContext(BaseModel):
    """A reply is meaningless without the post it answers."""
    reply_post_id: str
    text: str
    parent_post_id: str | None = None
    parent_author_handle: str | None = None
    parent_text: str | None = None
    conversation_id: str | None = None
    # AUDIT FIX (user_activity upgrade in the md): replies carry lang too —
    # geo/voice signal.
    lang: str | None = None
    published_at: datetime


class RetweetContext(BaseModel):
    """AUDIT FIX: RT originals (user_activity upgrade in the md).

    `rt @x: ...` captions are truncated on store; who the user amplifies and
    the full original text are niche signals Prompt 2 feeds the LLM.
    """

    retweet_post_id: str
    original_post_id: str | None = None
    original_author_handle: str | None = None
    original_text: str | None = None
    lang: str | None = None
    published_at: datetime


class CommentSample(BaseModel):
    """An inbound comment on one of the user's posts (or, later, a peer's winner)."""
    comment_post_id: str
    on_post_id: str
    on_post_owner: str                     # "self" or a peer handle
    author_handle: str
    author_followers: int | None = None
    author_location_raw: str | None = None
    author_bio: str | None = None          # truncate to BIO_SNIPPET_CHARS on store
    text: str
    lang: str | None = None
    likes: int | None = None
    created_at: datetime
    is_owner_reply: bool = False
    looks_spam: bool = False               # computed by rules (emoji-only, "gm", links, dupes)
    # AUDIT FIX (post_comments table column in the md).
    sampled_at: datetime | None = None


# --------------------------------------------------------------------------
# COMPUTED: deterministic features (code only)
# --------------------------------------------------------------------------
class CountedTerm(BaseModel):
    term: str
    count: int


class DeterministicFeatures(BaseModel):
    n_originals: int
    n_replies: int
    n_retweets: int
    n_quotes: int
    n_comments_received: int
    thin_history: bool                     # n_originals < MIN_ORIGINALS_FOR_INFERENCE

    top_ngrams: list[CountedTerm]          # 1-3 grams ranked by distinctiveness (TF-IDF style)
    top_hashtags: list[CountedTerm]
    top_cashtags: list[CountedTerm]
    top_mentions: list[CountedTerm]
    top_reply_targets: list[CountedTerm]   # handles the user replies to
    top_retweet_authors: list[CountedTerm]
    top_quote_authors: list[CountedTerm]
    top_commenters: list[CountedTerm]      # handles that comment on the user's posts
    top_domains: list[CountedTerm]         # outbound link domains

    lang_distribution: dict[str, float]    # e.g. {"en": 0.82, "pcm": 0.12}
    posting_hour_histogram_utc: list[int] = Field(min_length=24, max_length=24)
    inferred_utc_offset_hours: float | None = None   # corroboration only, weak signal
    currency_symbols: list[CountedTerm] = Field(default_factory=list)
    place_candidates: list[CountedTerm] = Field(default_factory=list)  # gazetteer hits


# --------------------------------------------------------------------------
# GEO MODEL: location means three different things. Keep them separate.
#   creator  = where the person is
#   audience = where the people who engage are
#   niche    = whether the topic itself is place-bound (Nigerian fintech vs AI tooling)
# --------------------------------------------------------------------------
class GeoEvidenceItem(BaseModel):
    source: GeoEvidenceSource
    detail: str                            # e.g. 'bio says "Port Harcourt"', '41% of commenters list NG'


class GeoSignal(BaseModel):
    scope: GeoScope
    level: GeoLevel
    value: str                             # ISO country code, region, or city name
    share: float | None = Field(default=None, ge=0, le=1)   # audience scopes: fraction
    confidence: float = Field(ge=0, le=1)
    evidence: list[GeoEvidenceItem] = Field(min_length=1)


class GeoProfile(BaseModel):
    creator: list[GeoSignal] = Field(default_factory=list)
    audience: list[GeoSignal] = Field(default_factory=list)
    niche: list[GeoSignal] = Field(default_factory=list)
    geo_relevance: GeoRelevance
    geo_relevance_reason: str
    user_confirmed: bool = False


# --------------------------------------------------------------------------
# LLM OUTPUT: niche synthesis
# --------------------------------------------------------------------------
class KeywordCandidate(BaseModel):
    term: str                              # canonical form, lowercase unless a proper noun
    type: KeywordType
    variants: list[str] = Field(default_factory=list, max_length=6)  # spellings, plurals, slang
    search_worthy: bool                    # would this surface peers if searched on X?
    rationale: str = Field(max_length=200)


class NicheQuery(BaseModel):
    tier: QueryTier
    query_text: str
    rationale: str = Field(max_length=200)
    uses_geo: bool = False
    target_language: str | None = None
    # AUDIT FIX (Prompt 2 post-processing): code dry-runs the best few queries and
    # records the outcome here — "kept but marked weak" needs somewhere to live.
    # None = not validated yet; never defaulted to a passing 0.
    validation_hits: int | None = None
    weak: bool = False                     # < MIN_QUERY_USABLE_HITS usable posts


class NicheLLMOutput(BaseModel):
    primary_niche: str                     # human label, e.g. "AI tools for African social media"
    niche_slug: str                        # lowercase-hyphen topic key, no geo in it
    secondary_niches: list[str] = Field(default_factory=list, max_length=3)
    creator_role: str                      # "founder", "designer", "educator", ...
    audience_description: str
    audience_roles: list[str] = Field(default_factory=list, max_length=5)
    keywords: list[KeywordCandidate] = Field(max_length=NicheConfig.MAX_KEYWORDS)
    geo: GeoProfile
    queries: list[NicheQuery] = Field(max_length=NicheConfig.MAX_QUERIES)
    missing_evidence: list[str] = Field(default_factory=list)
    needs_user_confirmation: list[NeedsConfirmation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _geo_queries_exist_when_local(self) -> NicheLLMOutput:
        if self.geo.geo_relevance == "local_first" and not any(q.uses_geo for q in self.queries):
            raise ValueError("local_first niche must include at least one geo-qualified query")
        return self


# --------------------------------------------------------------------------
# COMPUTED + STORED: scored keywords, peer seeds, final niche profile
# --------------------------------------------------------------------------
class KeywordEvidenceCounts(BaseModel):
    bio: int = 0
    original: int = 0
    quote: int = 0
    reply: int = 0
    retweet: int = 0
    comment_received: int = 0
    comment_on_peer: int = 0


class ScoredKeyword(BaseModel):
    term: str
    type: KeywordType
    variants: list[str] = Field(default_factory=list)
    weight: float = Field(ge=0, le=1)      # normalized across the profile's keywords
    evidence: KeywordEvidenceCounts
    example_post_ids: list[str] = Field(default_factory=list, max_length=3)
    search_worthy: bool
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class PeerSeed(BaseModel):
    """Built by code from the interaction graph. The LLM never invents handles."""
    handle: str
    source: SeedSource
    interaction_count: int
    reason: str


class NicheProfile(BaseModel):
    profile_id: int
    version: int
    extracted_at: datetime
    status: Literal["ok", "thin_history", "failed"]
    niche_key: str                         # f"{niche_slug}:{geo_scope}"  geo_scope = ISO country or "global"
    primary_niche: str
    niche_slug: str
    secondary_niches: list[str]
    creator_role: str
    audience_description: str
    audience_roles: list[str]
    keywords: list[ScoredKeyword]
    geo: GeoProfile
    queries: list[NicheQuery]
    peer_seeds: list[PeerSeed]
    confidence: float = Field(ge=0, le=1)
    needs_user_confirmation: list[NeedsConfirmation]
    missing_evidence: list[str] = Field(default_factory=list)
    user_overrides: dict = Field(default_factory=dict)   # confirmed values win over inferred
    # status "failed" or "thin_history" must carry NO fabricated niche. Ask the user instead.


# --------------------------------------------------------------------------
# PEER DISCOVERY + VETTING
# --------------------------------------------------------------------------
class PeerCandidate(BaseModel):
    handle: str
    followers: int | None = None
    bio: str | None = None
    location_raw: str | None = None
    discovery_sources: list[SeedSource]
    interaction_count: int = 0

    # computed
    size_ratio: float | None = None        # peer_followers / user_followers
    tier: PeerTier | None = None
    geo_match: bool | None = None          # None = unknown (no location signal)
    lang_match: bool | None = None
    overlap_score: float = Field(default=0, ge=0, le=1)  # keyword overlap with the user's niche
    last_post_at: datetime | None = None
    posts_per_week: float | None = None
    original_ratio: float | None = None    # originals / all posts (low = mostly RTs)
    bot_score: float = Field(default=0, ge=0, le=1)

    # llm_inferred (PeerVettingOutput) + final decision
    niche_fit: int | None = Field(default=None, ge=1, le=5)
    fit_reason: str | None = None
    flags: list[PeerFlag] = Field(default_factory=list)
    status: Literal["candidate", "vetted", "rejected"] = "candidate"
    reject_reason: str | None = None
    # AUDIT FIX (niche_peers table column in the md).
    last_verified: datetime | None = None


class PeerVettingItem(BaseModel):
    handle: str
    niche_fit: int = Field(ge=1, le=5)
    same_audience: bool
    reason: str = Field(max_length=200)
    flags: list[PeerFlag] = Field(default_factory=list)


class PeerVettingOutput(BaseModel):
    vetted: list[PeerVettingItem]


class NichePeerSet(BaseModel):
    """What the framework pipeline (app/schemas/peer.py) consumes."""
    niche_key: str
    generated_at: datetime
    peers: list[PeerCandidate]             # tier == "peer"
    aspirational: list[PeerCandidate]      # tier == "aspirational"
    giants: list[PeerCandidate]            # reference only, EXCLUDED from baselines/benchmarks
    warnings: list[str] = Field(default_factory=list)
