from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    platform: str = "x"  # MVP targets X only; column kept for extensibility
    handle: str
    pfm_account_id: str = Field(unique=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # --- profile-extract fixes (additive) ---
    # IANA name ("Africa/Lagos") when user-confirmed, or a weak inferred offset
    # like "UTC+01:00". Source: "inferred" (posting-hour histogram) |
    # "user_confirmed" (always wins; never overwritten by inference).
    timezone: str | None = None
    timezone_source: str | None = None


class ProfileSnapshot(SQLModel, table=True):
    """One row per ingestion pass: account size over time.

    followers/following are NULL until a profile-lookup capability is verified
    (Xpoz profile lookup / PFM get_social_account shape — niche Prompt 1 Step 0).
    Never fabricated: the row exists to timestamp the pass even when counts are unknown.
    """

    __tablename__ = "profile_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    captured_at: datetime
    followers: int | None = None
    following: int | None = None
    source: str | None = None  # "pfm" | "xpoz"


class ProfileBaseline(SQLModel, table=True):
    """Own-account baseline: median/p75 views over recent originals.

    Computed by app.analysis.metrics (the SAME functions the peer pipeline uses),
    using final_metrics (snapshot nearest 72h), excluding is_deleted_suspect
    posts and posts younger than PeerConfig.MIN_POST_AGE_HOURS.
    Append-only: one row per recomputation; latest row per profile wins.
    """

    __tablename__ = "profile_baseline"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    window_days: int = 90
    n_posts: int = 0
    median_views: float = 0.0
    median_engagement: float = 0.0
    p75_views: float = 0.0
    baseline_reliable: bool = False  # n_posts >= PeerConfig.MIN_ACCOUNT_SAMPLE
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
