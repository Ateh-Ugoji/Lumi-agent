"""Tables of INTELLIGENCE. See docs/SCHEMA.md section 7.

Table names, foreign keys with their ``on_delete``, unique constraints and CHECKs are fixed by the
schema; columns may be added. Chroma keeps only vectors that point at these ids (``post:<id>``,
``framework:<id>``, ``memory:<id>``), never documents.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Now

from apps.core.choices import Platform


def _in(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__in": choices.values})


def _nullable_in(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__isnull": True}) | _in(field, choices)


# -- voice -------------------------------------------------------------------


class VoiceSource(models.TextChoices):
    POSTS = "posts"
    QUESTIONS = "questions"


GENERAL = "general"
VOICE_PLATFORMS = [*Platform.values, GENERAL]


class VoiceProfile(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="voice_profiles",
    )
    # ``general`` instead of NULL so the unique constraint works without NULLS NOT DISTINCT.
    platform = models.CharField(max_length=20, db_default=GENERAL)
    version = models.IntegerField()
    is_current = models.BooleanField(db_default=False)
    source = models.CharField(max_length=10, choices=VoiceSource.choices)
    payload = models.JSONField()
    model = models.CharField(max_length=100, db_default="", blank=True)
    prompt_version = models.CharField(max_length=40, db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "voice_profiles"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "platform", "version"],
                name="uq_voice_profiles_version",
            ),
            models.UniqueConstraint(
                fields=["profile", "platform"],
                condition=Q(is_current=True),
                name="uq_voice_profiles_current",
            ),
            models.CheckConstraint(
                condition=Q(platform__in=VOICE_PLATFORMS),
                name="ck_voice_profiles_platform",
            ),
            models.CheckConstraint(
                condition=_in("source", VoiceSource), name="ck_voice_profiles_source"
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="ck_voice_profiles_version"
            ),
        ]


class VoiceProfileExample(models.Model):
    voice_profile = models.ForeignKey(
        VoiceProfile, on_delete=models.CASCADE, related_name="examples"
    )
    post = models.ForeignKey(
        "profiles.Post", on_delete=models.CASCADE, related_name="voice_examples"
    )
    position = models.SmallIntegerField()

    class Meta:
        db_table = "voice_profile_examples"
        constraints = [
            models.UniqueConstraint(
                fields=["voice_profile", "post"], name="uq_voice_examples_post"
            ),
        ]


class StyleAnswer(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile", on_delete=models.CASCADE, related_name="style_answers"
    )
    question_key = models.CharField(max_length=80)
    answer = models.TextField()
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        db_table = "style_answers"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "question_key"], name="uq_style_answers_question"
            ),
        ]


# -- niche -------------------------------------------------------------------


class NicheSource(models.TextChoices):
    USER = "user"
    INFERRED = "inferred"


class NichePreference(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="niche_preferences",
    )
    niche_key = models.CharField(max_length=120)  # "<slug>:<geo_scope>"
    title = models.CharField(max_length=200)
    source = models.CharField(max_length=10, choices=NicheSource.choices)
    is_active = models.BooleanField(db_default=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        db_table = "niche_preferences"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "niche_key"], name="uq_niche_preferences_key"
            ),
            models.UniqueConstraint(
                fields=["profile"],
                condition=Q(is_active=True),
                name="uq_niche_preferences_active",
            ),
            models.CheckConstraint(
                condition=_in("source", NicheSource), name="ck_niche_preferences_source"
            ),
        ]


class NichePreferenceKeyword(models.Model):
    preference = models.ForeignKey(
        NichePreference, on_delete=models.CASCADE, related_name="keywords"
    )
    keyword = models.CharField(max_length=100)

    class Meta:
        db_table = "niche_preference_keywords"
        constraints = [
            models.UniqueConstraint(
                "preference", Lower("keyword"), name="uq_niche_keywords_keyword"
            ),
        ]


class NichePreferenceHandle(models.Model):
    preference = models.ForeignKey(
        NichePreference, on_delete=models.CASCADE, related_name="handles"
    )
    handle = models.ForeignKey(
        "profiles.SocialHandle",
        on_delete=models.CASCADE,
        related_name="niche_preferences",
    )

    class Meta:
        db_table = "niche_preference_handles"
        constraints = [
            models.UniqueConstraint(
                fields=["preference", "handle"], name="uq_niche_handles_handle"
            ),
        ]


class TaggingStatus(models.TextChoices):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class PostTagging(models.Model):
    post = models.ForeignKey(
        "profiles.Post", on_delete=models.CASCADE, related_name="taggings"
    )
    prompt_version = models.CharField(max_length=40, db_default="", blank=True)
    status = models.CharField(
        max_length=10, choices=TaggingStatus.choices, db_default=TaggingStatus.PENDING
    )
    analysis = models.JSONField(null=True, blank=True)
    framework_guess = models.CharField(max_length=120, db_default="", blank=True)
    validation_error = models.TextField(db_default="", blank=True)
    tagged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "post_taggings"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "prompt_version"], name="uq_post_taggings_version"
            ),
            models.CheckConstraint(
                condition=_in("status", TaggingStatus), name="ck_post_taggings_status"
            ),
        ]


class ReportStatus(models.TextChoices):
    PENDING = "pending"
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"


class ReportOrigin(models.TextChoices):
    PIPELINE = "pipeline"
    LEGACY_PEER_FRAMEWORKS = "legacy_peer_frameworks"
    LEGACY_NICHE_REPORT = "legacy_niche_report"


class NicheReport(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile", on_delete=models.CASCADE, related_name="niche_reports"
    )
    query = models.TextField()
    niche = models.CharField(max_length=200)
    status = models.CharField(max_length=18, choices=ReportStatus.choices)
    posts_analyzed = models.IntegerField()
    winner_count = models.IntegerField()
    peers_analyzed = models.IntegerField()
    report = models.JSONField()  # raw validated model output
    origin = models.CharField(max_length=24, choices=ReportOrigin.choices)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "niche_reports"
        constraints = [
            models.CheckConstraint(
                condition=_in("status", ReportStatus), name="ck_niche_reports_status"
            ),
            models.CheckConstraint(
                condition=_in("origin", ReportOrigin), name="ck_niche_reports_origin"
            ),
            models.CheckConstraint(
                condition=Q(posts_analyzed__gte=0)
                & Q(winner_count__gte=0)
                & Q(peers_analyzed__gte=0),
                name="ck_niche_reports_counts",
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-created_at"], name="ix_niche_reports_recent"
            )
        ]


class NicheReportPeer(models.Model):
    report = models.ForeignKey(
        NicheReport, on_delete=models.CASCADE, related_name="peers"
    )
    handle = models.ForeignKey(
        "profiles.SocialHandle",
        on_delete=models.CASCADE,
        related_name="niche_report_peers",
    )

    class Meta:
        db_table = "niche_report_peers"
        constraints = [
            models.UniqueConstraint(
                fields=["report", "handle"], name="uq_niche_report_peers_handle"
            ),
        ]


class Framework(models.Model):
    report = models.ForeignKey(
        NicheReport, on_delete=models.CASCADE, related_name="frameworks"
    )
    name = models.CharField(max_length=160)
    description = models.TextField()
    lift = models.FloatField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    payload = models.JSONField(null=True, blank=True)
    ordinal = models.SmallIntegerField()

    class Meta:
        db_table = "frameworks"
        constraints = [
            models.UniqueConstraint(
                fields=["report", "ordinal"], name="uq_frameworks_ordinal"
            ),
            models.CheckConstraint(
                condition=Q(confidence__isnull=True)
                | (Q(confidence__gte=0) & Q(confidence__lte=1)),
                name="ck_frameworks_confidence",
            ),
        ]


class FrameworkEvidence(models.Model):
    framework = models.ForeignKey(
        Framework, on_delete=models.CASCADE, related_name="evidence"
    )
    post = models.ForeignKey(
        "profiles.Post", on_delete=models.CASCADE, related_name="framework_evidence"
    )

    class Meta:
        db_table = "framework_evidence"
        constraints = [
            models.UniqueConstraint(
                fields=["framework", "post"], name="uq_framework_evidence_post"
            ),
        ]


# -- repurpose and generation ------------------------------------------------


class RouteLabel(models.TextChoices):
    EASY = "easy"
    STANDARD = "standard"
    HARD = "hard"


class RequestMode(models.TextChoices):
    REPURPOSE = "repurpose"
    TOPIC = "topic"


class RepurposeRequest(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="repurpose_requests",
    )
    source_caption = models.TextField()
    source_post = models.ForeignKey(
        "profiles.Post",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repurpose_requests",
    )
    route_label = models.CharField(
        max_length=10, choices=RouteLabel.choices, null=True, blank=True
    )
    # Added by INTELLIGENCE for generation from a topic (``source_caption`` holds the topic).
    mode = models.CharField(
        max_length=10, choices=RequestMode.choices, db_default=RequestMode.REPURPOSE
    )
    brief = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "repurpose_requests"
        constraints = [
            models.CheckConstraint(
                condition=_nullable_in("route_label", RouteLabel),
                name="ck_repurpose_requests_route",
            ),
            models.CheckConstraint(
                condition=_in("mode", RequestMode), name="ck_repurpose_requests_mode"
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-created_at"], name="ix_repurpose_req_recent"
            )
        ]


class JudgeVerdict(models.TextChoices):
    YES = "yes"
    NO = "no"


class RepurposeAttempt(models.Model):
    """The draft the user reviews in React."""

    request = models.ForeignKey(
        RepurposeRequest, on_delete=models.CASCADE, related_name="attempts"
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    tier = models.CharField(max_length=10, null=True, blank=True)
    model = models.CharField(max_length=100, null=True, blank=True)
    provider = models.CharField(max_length=20, null=True, blank=True)
    attempt_no = models.SmallIntegerField()
    output = models.TextField()
    must_keep_passed = models.BooleanField()
    judge_verdict = models.CharField(
        max_length=3, choices=JudgeVerdict.choices, null=True, blank=True
    )
    judge_confidence = models.FloatField(null=True, blank=True)
    is_fallback = models.BooleanField(db_default=False)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "repurpose_attempts"
        constraints = [
            models.UniqueConstraint(
                fields=["request", "platform", "attempt_no"],
                name="uq_repurpose_attempts_no",
            ),
            models.CheckConstraint(
                condition=_in("platform", Platform),
                name="ck_repurpose_attempts_platform",
            ),
            models.CheckConstraint(
                condition=_nullable_in("judge_verdict", JudgeVerdict),
                name="ck_repurpose_attempts_verdict",
            ),
            models.CheckConstraint(
                condition=Q(judge_confidence__isnull=True)
                | (Q(judge_confidence__gte=0) & Q(judge_confidence__lte=1)),
                name="ck_repurpose_attempts_conf",
            ),
            models.CheckConstraint(
                condition=Q(attempt_no__gte=1), name="ck_repurpose_attempts_no"
            ),
        ]


class Decision(models.TextChoices):
    PASS = "pass"
    REGENERATE = "regenerate"
    FAIL = "fail"


class GenerationEvaluation(models.Model):
    attempt = models.ForeignKey(
        RepurposeAttempt, on_delete=models.CASCADE, related_name="evaluations"
    )
    style_score = models.FloatField(null=True, blank=True)
    decision = models.CharField(max_length=10, choices=Decision.choices)
    evaluation = models.JSONField()
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "generation_evaluations"
        constraints = [
            models.CheckConstraint(
                condition=_in("decision", Decision),
                name="ck_generation_evals_decision",
            ),
            models.CheckConstraint(
                condition=Q(style_score__isnull=True)
                | (Q(style_score__gte=0) & Q(style_score__lte=1)),
                name="ck_generation_evals_style",
            ),
        ]
        indexes = [models.Index(fields=["attempt"], name="ix_generation_evals_attempt")]


class UserActionKind(models.TextChoices):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


class UserAction(models.Model):
    attempt = models.ForeignKey(
        RepurposeAttempt, on_delete=models.CASCADE, related_name="user_actions"
    )
    action = models.CharField(max_length=6, choices=UserActionKind.choices)
    edited_text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "user_actions"
        constraints = [
            models.CheckConstraint(
                condition=_in("action", UserActionKind), name="ck_user_actions_action"
            ),
            models.CheckConstraint(
                condition=(Q(action=UserActionKind.EDIT) & Q(edited_text__isnull=False))
                | (~Q(action=UserActionKind.EDIT) & Q(edited_text__isnull=True)),
                name="ck_user_actions_edited",
            ),
        ]


# -- routing, requests, memory, video ----------------------------------------


class PathTaken(models.TextChoices):
    FAST = "fast"
    FULL = "full"


class TurnClassification(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="turn_classifications",
    )
    message = models.ForeignKey(
        "chat.ChatMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classifications",
    )
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    message_text_hash = models.CharField(max_length=64, db_default="", blank=True)
    message_preview = models.TextField(db_default="", blank=True)  # first 160 chars
    path_taken = models.CharField(
        max_length=4, choices=PathTaken.choices, null=True, blank=True
    )
    rule_class = models.CharField(max_length=30, db_default="other")
    rule_matched = models.CharField(max_length=80, null=True, blank=True)
    jev_called = models.BooleanField(db_default=False)
    jev_class = models.CharField(max_length=30, null=True, blank=True)
    jev_probs = models.JSONField(null=True, blank=True)
    jev_confidence = models.FloatField(null=True, blank=True)
    jev_latency_ms = models.IntegerField(null=True, blank=True)
    jev_error = models.TextField(null=True, blank=True)
    final_class = models.CharField(max_length=30, db_default="other")
    tools_called = ArrayField(models.TextField(), null=True, blank=True)
    credits_spent = models.FloatField(
        null=True, blank=True
    )  # no meter yet: NULL, never 0
    total_latency_ms = models.IntegerField(null=True, blank=True)
    user_corrected = models.BooleanField(null=True, blank=True)
    timings = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "turn_classifications"
        constraints = [
            models.CheckConstraint(
                condition=_nullable_in("path_taken", PathTaken),
                name="ck_turn_classifications_path",
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-created_at"], name="ix_turn_class_recent"
            ),
            models.Index(fields=["message"], name="ix_turn_class_message"),
        ]


class UserSearchRequest(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="user_search_requests",
    )
    # The platform is the handle's.
    handle = models.ForeignKey(
        "profiles.SocialHandle",
        on_delete=models.CASCADE,
        related_name="user_search_requests",
    )
    request_note = models.TextField(db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "user_search_requests"
        indexes = [
            models.Index(
                fields=["profile", "-created_at"], name="ix_user_search_recent"
            )
        ]


class MemoryNote(models.Model):
    profile = models.ForeignKey(
        "profiles.SocialProfile", on_delete=models.CASCADE, related_name="memory_notes"
    )
    kind = models.CharField(max_length=20)
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    last_accessed_at = models.DateTimeField(db_default=Now())
    access_count = models.IntegerField(db_default=0)

    class Meta:
        db_table = "memory_notes"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "content_hash"], name="uq_memory_notes_hash"
            ),
            models.CheckConstraint(
                condition=Q(access_count__gte=0), name="ck_memory_notes_access"
            ),
        ]


class ProfileMemorySummary(models.Model):
    profile = models.OneToOneField(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="memory_summary",
    )
    summary_md = models.TextField()
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        db_table = "profile_memory_summaries"


class VideoAnalysisStatus(models.TextChoices):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class VideoAnalysisRecord(models.Model):
    media = models.ForeignKey(
        "profiles.PostMedia",
        on_delete=models.CASCADE,
        related_name="video_analyses",
    )
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=40)
    status = models.CharField(max_length=10, choices=VideoAnalysisStatus.choices)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "video_analysis_records"
        constraints = [
            models.UniqueConstraint(
                fields=["media", "provider", "prompt_version"],
                name="uq_video_analysis_cache",
            ),
            models.CheckConstraint(
                condition=_in("status", VideoAnalysisStatus),
                name="ck_video_analysis_status",
            ),
        ]
