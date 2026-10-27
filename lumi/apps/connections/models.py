"""Tables of the connections app. See docs/SCHEMA.md section 8 and docs/CONTRATOS.md section 11.

Every token and every PKCE verifier is stored with ``EncryptedTextField``. Nothing here is
filterable by token value, by design.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

from apps.core.choices import Platform
from apps.core.fields import EncryptedTextField
from apps.core.models import TimestampedModel
from apps.profiles.models import SocialHandle, SocialProfile


def _in(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__in": choices.values})


class Provider(models.TextChoices):
    PFM = "pfm"
    META = "meta"
    LINKEDIN = "linkedin"
    X = "x"


class AccountStatus(models.TextChoices):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    LIMITED = "limited"
    ERROR = "error"


class PublishStatus(models.TextChoices):
    """Not ``JobStatus``: ``unknown`` means nobody knows whether the provider published."""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ConnectedAccount(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connected_accounts",
    )
    social_profile = models.ForeignKey(
        SocialProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="connected_accounts",
    )
    provider = models.CharField(max_length=12, choices=Provider.choices)
    external_account_id = models.CharField(max_length=128)
    # Network of the account. Needed for pfm, where one provider fronts many networks.
    platform = models.CharField(max_length=20, db_default="", blank=True)
    display_name = models.CharField(max_length=200, db_default="", blank=True)
    handle = models.CharField(max_length=100, db_default="", blank=True)
    status = models.CharField(
        max_length=10, choices=AccountStatus.choices, db_default=AccountStatus.ACTIVE
    )
    scopes = ArrayField(models.TextField(), db_default=[], blank=True)
    access_token = EncryptedTextField(db_default="", blank=True)
    refresh_token = EncryptedTextField(db_default="", blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(db_default="", blank=True)

    class Meta:
        db_table = "connected_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_account_id"],
                name="uq_connected_accounts_ext",
            ),
            models.UniqueConstraint(
                fields=["social_profile", "provider"],
                condition=Q(social_profile__isnull=False),
                name="uq_connected_accounts_profile",
            ),
            models.CheckConstraint(
                condition=_in("provider", Provider),
                name="ck_connected_accounts_provider",
            ),
            models.CheckConstraint(
                condition=_in("status", AccountStatus),
                name="ck_connected_accounts_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "provider"], name="ix_connected_accounts_user"
            ),
            models.Index(fields=["expires_at"], name="ix_connected_accounts_expiry"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_account_id}"


class OAuthState(models.Model):
    state = models.CharField(max_length=128)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oauth_states"
    )
    provider = models.CharField(max_length=12)
    # Profile the account will be linked to once the callback succeeds.
    social_profile = models.ForeignKey(
        SocialProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="oauth_states",
    )
    code_verifier = EncryptedTextField(db_default="", blank=True)
    redirect_after = models.TextField(db_default="/", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "oauth_states"
        constraints = [
            models.UniqueConstraint(fields=["state"], name="uq_oauth_states_state"),
        ]
        indexes = [models.Index(fields=["expires_at"], name="ix_oauth_states_expiry")]


class PublishJob(models.Model):
    profile = models.ForeignKey(
        SocialProfile, on_delete=models.CASCADE, related_name="publish_jobs"
    )
    connected_account = models.ForeignKey(
        ConnectedAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publish_jobs",
    )
    attempt = models.ForeignKey(
        "intelligence.RepurposeAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publish_jobs",
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    text = models.TextField()
    status = models.CharField(
        max_length=10, choices=PublishStatus.choices, db_default=PublishStatus.PENDING
    )
    fingerprint = models.CharField(max_length=64)
    external_post_id = models.CharField(max_length=128, db_default="", blank=True)
    external_url = models.TextField(db_default="", blank=True)
    error = models.TextField(db_default="", blank=True)
    idempotency_key = models.CharField(max_length=128)
    dry_run = models.BooleanField(db_default=False)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        db_table = "publish_jobs"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "idempotency_key"], name="uq_publish_jobs_idem"
            ),
            models.CheckConstraint(
                condition=_in("status", PublishStatus), name="ck_publish_jobs_status"
            ),
            models.CheckConstraint(
                condition=_in("platform", Platform), name="ck_publish_jobs_platform"
            ),
            models.CheckConstraint(
                condition=Q(fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="ck_publish_jobs_fingerprint",
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "-created_at"], name="ix_publish_jobs_recent"
            )
        ]


class McpAuthAccount(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_auth_accounts",
    )
    account = models.CharField(max_length=40)
    access_token = EncryptedTextField(db_default="", blank=True)
    refresh_token = EncryptedTextField(db_default="", blank=True)
    token_type = models.CharField(max_length=20, db_default="Bearer")
    scopes = ArrayField(models.TextField(), db_default=[], blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        db_table = "mcp_auth_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "account"], name="uq_mcp_auth_accounts_user"
            )
        ]


class HandleSearchCache(models.Model):
    platform = models.CharField(max_length=20, choices=Platform.choices)
    query_normalized = models.CharField(max_length=100)
    fetched_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "handle_search_cache"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "query_normalized"], name="uq_handle_cache_query"
            ),
            models.CheckConstraint(
                condition=_in("platform", Platform), name="ck_handle_cache_platform"
            ),
        ]
        indexes = [
            models.Index(
                fields=["platform", "query_normalized"],
                opclasses=["varchar_pattern_ops", "varchar_pattern_ops"],
                name="ix_handle_cache_prefix",
            )
        ]


class HandleSearchCacheEntry(models.Model):
    cache = models.ForeignKey(
        HandleSearchCache, on_delete=models.CASCADE, related_name="entries"
    )
    handle = models.ForeignKey(
        SocialHandle, on_delete=models.CASCADE, related_name="search_cache_entries"
    )
    rank = models.PositiveSmallIntegerField(db_default=0)

    class Meta:
        db_table = "handle_search_cache_entries"
        constraints = [
            models.UniqueConstraint(
                fields=["cache", "handle"], name="uq_handle_cache_entry"
            )
        ]
        ordering = ["rank", "id"]


class XpozCreditLedger(models.Model):
    """One row per paid Xpoz call. The key is identified by slot (1 or 2), never by value."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="xpoz_credit_entries",
    )
    provider = models.CharField(max_length=12, db_default="xpoz")
    route = models.CharField(max_length=60)
    credits = models.PositiveIntegerField()
    key_slot = models.PositiveSmallIntegerField()
    run_id = models.CharField(max_length=64, db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "xpoz_credit_ledger"
        constraints = [
            models.CheckConstraint(
                condition=Q(key_slot__in=[1, 2]), name="ck_xpoz_ledger_slot"
            )
        ]
        indexes = [models.Index(fields=["-created_at"], name="ix_xpoz_ledger_recent")]
