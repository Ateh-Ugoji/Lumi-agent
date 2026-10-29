"""Handles, profiles, posts, metrics, alerts. See docs/SCHEMA.md section 6.3."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Now

from apps.core.choices import IngestSource, Platform, PostKind
from apps.core.models import TimestampedModel

HANDLE_RE = r"^[a-z0-9._-]{1,100}$"


def _in(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__in": choices.values})


def _nullable_in(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__isnull": True}) | _in(field, choices)


def _nonneg(*fields: str) -> Q:
    """NULL or >= 0 for every field. A missing metric is NULL, never 0."""
    q = Q()
    for name in fields:
        q &= Q(**{f"{name}__isnull": True}) | Q(**{f"{name}__gte": 0})
    return q


class HandleOrigin(models.TextChoices):
    PROFILE = "profile"
    LIVE = "live"
    CACHE = "cache"
    SELECTED = "selected"
    NICHE = "niche"
    IMPORT = "import"


class SocialHandle(TimestampedModel):
    """Public identity on a platform, shared by every user that follows it."""

    platform = models.CharField(max_length=20, choices=Platform.choices)
    handle_normalized = models.CharField(max_length=100)
    handle_display = models.CharField(max_length=100, db_default="", blank=True)
    display_name = models.CharField(max_length=200, db_default="", blank=True)
    avatar_url = models.TextField(db_default="", blank=True)
    external_id = models.CharField(max_length=64, db_default="", blank=True)
    follower_count = models.BigIntegerField(null=True, blank=True)
    follower_count_at = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(
        max_length=12, choices=HandleOrigin.choices, db_default=HandleOrigin.LIVE
    )
    last_seen_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "social_handles"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "handle_normalized"],
                name="uq_social_handles_platform_handle",
            ),
            models.CheckConstraint(
                condition=_in("platform", Platform), name="ck_social_handles_platform"
            ),
            models.CheckConstraint(
                condition=Q(handle_normalized=Lower("handle_normalized"))
                & Q(handle_normalized__regex=HANDLE_RE),
                name="ck_social_handles_normalized",
            ),
            models.CheckConstraint(
                condition=_in("origin", HandleOrigin), name="ck_social_handles_origin"
            ),
            models.CheckConstraint(
                condition=_nonneg("follower_count"), name="ck_social_handles_followers"
            ),
        ]
        indexes = [
            models.Index(
                fields=["platform", "handle_normalized"],
                opclasses=["varchar_pattern_ops", "varchar_pattern_ops"],
                name="ix_social_handles_prefix",
            ),
            models.Index(fields=["-last_seen_at"], name="ix_social_handles_last_seen"),
        ]

    def __str__(self) -> str:
        return f"{self.platform}:{self.handle_normalized}"


class HandleSnapshot(models.Model):
    handle = models.ForeignKey(
        SocialHandle, on_delete=models.CASCADE, related_name="snapshots"
    )
    captured_at = models.DateTimeField(db_default=Now())
    followers = models.BigIntegerField(null=True, blank=True)
    following = models.BigIntegerField(null=True, blank=True)
    source = models.CharField(
        max_length=12, choices=IngestSource.choices, null=True, blank=True
    )

    class Meta:
        db_table = "handle_snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=["handle", "captured_at"],
                name="uq_handle_snapshots_handle_captured",
            ),
            models.CheckConstraint(
                condition=_nonneg("followers", "following"),
                name="ck_handle_snapshots_nonneg",
            ),
            models.CheckConstraint(
                condition=_nullable_in("source", IngestSource),
                name="ck_handle_snapshots_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["handle", "-captured_at"], name="ix_handle_snapshots_recent"
            )
        ]


class TimezoneSource(models.TextChoices):
    INFERRED = "inferred"
    USER_CONFIRMED = "user_confirmed"


class SocialProfile(TimestampedModel):
    """The profile a user works with: their own account on one network."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_profiles",
    )
    handle = models.ForeignKey(
        SocialHandle, on_delete=models.PROTECT, related_name="social_profiles"
    )
    timezone = models.CharField(max_length=64, null=True, blank=True)
    timezone_source = models.CharField(
        max_length=16, choices=TimezoneSource.choices, null=True, blank=True
    )
    bootstrapped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "social_profiles"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "handle"], name="uq_social_profiles_user_handle"
            ),
            models.CheckConstraint(
                condition=(
                    Q(timezone__isnull=True, timezone_source__isnull=True)
                    | (
                        Q(timezone__isnull=False, timezone_source__isnull=False)
                        & _in("timezone_source", TimezoneSource)
                    )
                ),
                name="ck_social_profiles_timezone",
            ),
        ]


class ProfileBaseline(models.Model):
    """Insert-only. The newest row by ``computed_at`` is the current baseline."""

    profile = models.ForeignKey(
        SocialProfile, on_delete=models.CASCADE, related_name="baselines"
    )
    window_days = models.SmallIntegerField(db_default=90)
    n_posts = models.IntegerField(db_default=0)
    median_views = models.FloatField(db_default=0)
    median_engagement = models.FloatField(db_default=0)
    p75_views = models.FloatField(db_default=0)
    baseline_reliable = models.BooleanField(db_default=False)
    computed_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "profile_baselines"
        constraints = [
            models.CheckConstraint(
                condition=Q(window_days__gt=0), name="ck_profile_baselines_window"
            ),
            models.CheckConstraint(
                condition=Q(
                    n_posts__gte=0,
                    median_views__gte=0,
                    median_engagement__gte=0,
                    p75_views__gte=0,
                ),
                name="ck_profile_baselines_nonneg",
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-computed_at"], name="ix_profile_baselines_computed"
            )
        ]


class PollConfig(TimestampedModel):
    profile = models.OneToOneField(
        SocialProfile, on_delete=models.CASCADE, related_name="poll_config"
    )
    interval_minutes = models.SmallIntegerField(db_default=5)
    is_active = models.BooleanField(db_default=False)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "poll_configs"
        constraints = [
            models.CheckConstraint(
                condition=Q(interval_minutes__range=(1, 1440)),
                name="ck_poll_configs_interval",
            ),
        ]
        indexes = [
            models.Index(
                fields=["last_polled_at"],
                condition=Q(is_active=True),
                name="ix_poll_configs_due",
            ),
        ]


class ListeningKeyword(models.Model):
    profile = models.ForeignKey(
        SocialProfile, on_delete=models.CASCADE, related_name="listening_keywords"
    )
    keyword = models.CharField(max_length=100)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "listening_keywords"
        constraints = [
            models.UniqueConstraint(
                "profile",
                Lower("keyword"),
                name="uq_listening_keywords_profile_keyword",
            ),
            models.CheckConstraint(
                condition=Q(keyword=models.Func(F("keyword"), function="btrim"))
                & ~Q(keyword=""),
                name="ck_listening_keywords_not_blank",
            ),
        ]


class KindSource(models.TextChoices):
    API = "api"
    HEURISTIC = "heuristic"


class Post(TimestampedModel):
    """Own and third-party posts in one table. A post is the profile's own when
    ``author_id == profile.handle_id``."""

    author = models.ForeignKey(
        SocialHandle, on_delete=models.CASCADE, related_name="posts"
    )
    platform_post_id = models.CharField(max_length=64)
    kind = models.CharField(
        max_length=10, choices=PostKind.choices, db_default=PostKind.ORIGINAL
    )
    kind_source = models.CharField(
        max_length=10, choices=KindSource.choices, null=True, blank=True
    )
    caption = models.TextField(db_default="", blank=True)
    url = models.TextField(db_default="", blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    is_stub = models.BooleanField(db_default=False)
    source = models.CharField(
        max_length=12, choices=IngestSource.choices, null=True, blank=True
    )
    conversation_id = models.CharField(max_length=64, db_default="", blank=True)
    language = models.CharField(max_length=12, db_default="", blank=True)
    thread_position = models.SmallIntegerField(null=True, blank=True)
    is_thread_head = models.BooleanField(null=True, blank=True)
    text_truncated = models.BooleanField(db_default=False)
    is_deleted_suspect = models.BooleanField(db_default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # Last time a check read this post's metrics, whether or not a snapshot was stored. A post
    # whose numbers did not move still gets a fresh stamp; NULL means nobody has checked it.
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posts"
        constraints = [
            models.UniqueConstraint(
                fields=["author", "platform_post_id"],
                name="uq_posts_author_platform_post",
            ),
            models.CheckConstraint(
                condition=_in("kind", PostKind), name="ck_posts_kind"
            ),
            models.CheckConstraint(
                condition=_nullable_in("kind_source", KindSource),
                name="ck_posts_kind_source",
            ),
            models.CheckConstraint(
                condition=_nullable_in("source", IngestSource), name="ck_posts_source"
            ),
            models.CheckConstraint(
                condition=Q(thread_position__isnull=True) | Q(thread_position__gte=1),
                name="ck_posts_thread_position",
            ),
        ]
        indexes = [
            models.Index(
                fields=["author", "-published_at"], name="ix_posts_author_published"
            ),
            models.Index(
                fields=["author", "-published_at"],
                condition=Q(kind=PostKind.ORIGINAL, is_deleted_suspect=False),
                name="ix_posts_author_original",
            ),
            models.Index(
                fields=["conversation_id"],
                condition=~Q(conversation_id=""),
                name="ix_posts_conversation",
            ),
        ]


class MediaKind(models.TextChoices):
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"


class PostMedia(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="media")
    position = models.SmallIntegerField(db_default=0)
    # NULL means "type unknown" (ports 1.9): some sources send a bare URL. Never guessed.
    kind = models.CharField(
        max_length=8, choices=MediaKind.choices, null=True, blank=True
    )
    url = models.TextField()
    thumbnail_url = models.TextField(db_default="", blank=True)
    duration_seconds = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "post_media"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "position"], name="uq_post_media_post_position"
            ),
            models.CheckConstraint(
                condition=_nullable_in("kind", MediaKind), name="ck_post_media_kind"
            ),
            models.CheckConstraint(
                condition=Q(duration_seconds__isnull=True) | Q(duration_seconds__gt=0),
                name="ck_post_media_duration",
            ),
            models.CheckConstraint(
                condition=(Q(width__isnull=True) | Q(width__gt=0))
                & (Q(height__isnull=True) | Q(height__gt=0)),
                name="ck_post_media_size",
            ),
        ]
        indexes = [
            models.Index(
                fields=["post"],
                condition=Q(kind=MediaKind.VIDEO),
                name="ix_post_media_video",
            )
        ]


class MetricSnapshot(models.Model):
    """Insert-only. ``age_hours`` is derived: ``captured_at - posts.published_at``."""

    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="metric_snapshots"
    )
    captured_at = models.DateTimeField(db_default=Now())
    source = models.CharField(
        max_length=12, choices=IngestSource.choices, null=True, blank=True
    )
    likes = models.BigIntegerField(null=True, blank=True)
    comments = models.BigIntegerField(null=True, blank=True)
    shares = models.BigIntegerField(null=True, blank=True)
    views = models.BigIntegerField(null=True, blank=True)
    bookmarks = models.BigIntegerField(null=True, blank=True)
    quotes = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "metric_snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "captured_at"], name="uq_metric_snapshots_post_captured"
            ),
            models.CheckConstraint(
                condition=_nonneg(
                    "likes", "comments", "shares", "views", "bookmarks", "quotes"
                ),
                name="ck_metric_snapshots_nonneg",
            ),
            models.CheckConstraint(
                condition=_nullable_in("source", IngestSource),
                name="ck_metric_snapshots_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["post", "-captured_at"], name="ix_metric_snapshots_recent"
            )
        ]


class AlertKind(models.TextChoices):
    SPIKE = "spike"
    NICHE_MATCH = "niche_match"


class AlertTrigger(models.TextChoices):
    VELOCITY = "velocity"
    JEV_BACKSTOP = "jev_backstop"
    SCAN = "scan"


class AlertStatus(models.TextChoices):
    ACTIVE = "active"
    DISMISSED = "dismissed"


class Alert(models.Model):
    profile = models.ForeignKey(
        SocialProfile, on_delete=models.CASCADE, related_name="alerts"
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="alerts")
    kind = models.CharField(max_length=12, choices=AlertKind.choices)
    trigger = models.CharField(
        max_length=16, choices=AlertTrigger.choices, null=True, blank=True
    )
    status = models.CharField(
        max_length=10, choices=AlertStatus.choices, db_default=AlertStatus.ACTIVE
    )
    velocity = models.FloatField(null=True, blank=True)
    baseline_velocity = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "alerts"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "post", "kind"],
                condition=Q(status=AlertStatus.ACTIVE),
                name="uq_alerts_one_active",
            ),
            models.CheckConstraint(
                condition=_in("kind", AlertKind), name="ck_alerts_kind"
            ),
            models.CheckConstraint(
                condition=_nullable_in("trigger", AlertTrigger),
                name="ck_alerts_trigger",
            ),
            models.CheckConstraint(
                condition=_in("status", AlertStatus), name="ck_alerts_status"
            ),
            models.CheckConstraint(
                condition=Q(dismissed_at__isnull=True)
                | Q(status=AlertStatus.DISMISSED),
                name="ck_alerts_dismissed",
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-created_at"],
                condition=Q(status=AlertStatus.ACTIVE),
                name="ix_alerts_profile_active",
            ),
        ]


class ListeningMatch(models.Model):
    profile = models.ForeignKey(
        SocialProfile, on_delete=models.CASCADE, related_name="listening_matches"
    )
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="listening_matches"
    )
    discovered_at = models.DateTimeField(db_default=Now())
    score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "listening_matches"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "post"], name="uq_listening_matches_profile_post"
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-discovered_at"], name="ix_listening_matches_recent"
            )
        ]
