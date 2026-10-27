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

from apps.core.choices import IngestSource, Platform
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
    GOOGLE = "google"


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


class PfmLink(models.Model):
    """The ``external_id`` Lumi gave Post for Me for one user.

    The value is random, so nobody can derive it from a user id. A sync accepts only accounts
    PFM reports under this exact value. Users who connected before this table existed keep the
    old ``lumi-user-<id>`` value, because PFM refuses to change the id of a connected account.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pfm_link"
    )
    external_id = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "pfm_links"


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


class McpPendingWrite(models.Model):
    """A write the model asked for and the user has not confirmed yet.

    One per profile: a newer request replaces the older one. It lives here, not in process
    memory, so it survives several workers and restarts. The claim is an atomic delete.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_pending_writes",
    )
    social_profile = models.OneToOneField(
        SocialProfile, on_delete=models.CASCADE, related_name="mcp_pending_write"
    )
    tool = models.CharField(max_length=200)
    server_tool = models.CharField(max_length=200)
    arguments = models.JSONField(db_default={}, default=dict)
    summary = models.TextField(db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "mcp_pending_writes"
        indexes = [models.Index(fields=["expires_at"], name="ix_mcp_pending_expiry")]


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


class UserSavedHandle(models.Model):
    """A handle one user picked in the handle search (``POST /handles/select``).

    ``social_handles`` is a shared cache of public identities, so who saved what lives here,
    one row per ``(user, handle)``. ``GET /handles/saved`` reads only the caller's rows.
    """

    # ``uq_user_saved_handle`` starts with user_id, so it already serves every lookup by user.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_handles",
        db_index=False,
    )
    handle = models.ForeignKey(
        SocialHandle, on_delete=models.CASCADE, related_name="saved_by"
    )
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "user_saved_handles"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "handle"], name="uq_user_saved_handle"
            )
        ]


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


class IngestPass(models.Model):
    """One read of an account's posts. The next pass uses the last complete one to tell a
    post that missed twice from a post that missed once (``connections/passes.py``)."""

    handle = models.ForeignKey(
        SocialHandle, on_delete=models.CASCADE, related_name="ingest_passes"
    )
    started_at = models.DateTimeField()
    source = models.CharField(max_length=12)
    complete = models.BooleanField()
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "ingest_passes"
        constraints = [
            models.UniqueConstraint(
                fields=["handle", "started_at"], name="uq_ingest_pass_handle_start"
            ),
            models.CheckConstraint(
                condition=_in("source", IngestSource), name="ck_ingest_pass_source"
            ),
        ]
        indexes = [
            models.Index(
                fields=["handle", "-started_at"],
                condition=Q(complete=True),
                name="ix_ingest_pass_complete",
            )
        ]


class ServiceKind(models.TextChoices):
    SOCIAL = "social"
    AGGREGATOR = "aggregator"
    DATA = "data"
    LLM = "llm"
    WORKSPACE = "workspace"


class ServiceAuth(models.TextChoices):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BEARER = "bearer"


class CredentialEnv(models.TextChoices):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Service(TimestampedModel):
    """Catalog of the outside services Lumi holds app credentials for.

    One row per credential OWNER, not per network: Facebook uses the ``meta`` app, Instagram and
    TikTok go through ``pfm``. ``code`` matches ``Provider`` for the five that connect accounts.
    """

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=ServiceKind.choices)
    auth_type = models.CharField(max_length=10, choices=ServiceAuth.choices)
    # False = listed but not usable yet (no adapter, or switched off on purpose).
    is_active = models.BooleanField(db_default=True)
    docs_url = models.TextField(db_default="", blank=True)

    class Meta:
        db_table = "services"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uq_services_code"),
            models.CheckConstraint(
                condition=_in("kind", ServiceKind), name="ck_services_kind"
            ),
            models.CheckConstraint(
                condition=_in("auth_type", ServiceAuth), name="ck_services_auth_type"
            ),
        ]

    def __str__(self) -> str:
        return self.code


_FORBIDDEN_EXTRA_WORDS = ("secret", "token", "password", "passwd", "api_key", "apikey", "private")


class ServiceCredential(TimestampedModel):
    """The app-level credential of a service (Lumi's own app, not a user's account).

    ``app_id`` is the public client id (plain text). ``app_secret`` is the secret, encrypted with
    ``EncryptedTextField``; for ``api_key`` and ``bearer`` services there is no client id, so
    ``app_id`` stays empty and ``app_secret`` holds the key or token. Per-user tokens live in
    ``connected_accounts`` and ``mcp_auth_accounts``, never here.
    """

    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name="credentials"
    )
    app_id = models.TextField(db_default="", blank=True)
    app_secret = EncryptedTextField(db_default="", blank=True)
    label = models.CharField(max_length=60, db_default="", blank=True)
    environment = models.CharField(
        max_length=12,
        choices=CredentialEnv.choices,
        db_default=CredentialEnv.DEVELOPMENT,
    )
    # Settings that are not secret: redirect URI, scopes, API version. Never filtered on.
    extra = models.JSONField(db_default={}, blank=True)
    # Last 4 characters of a long secret, to tell two keys apart without decrypting. Blank for
    # short secrets, where 4 characters would give too much away.
    secret_hint = models.CharField(max_length=4, db_default="", blank=True)
    is_active = models.BooleanField(db_default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_check_ok = models.BooleanField(null=True, blank=True)
    last_error = models.TextField(db_default="", blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_credentials_updated",
    )

    class Meta:
        db_table = "service_credentials"
        constraints = [
            models.UniqueConstraint(
                fields=["service", "environment"],
                condition=Q(is_active=True),
                name="uq_service_credentials_active",
            ),
            models.CheckConstraint(
                condition=_in("environment", CredentialEnv),
                name="ck_service_credentials_env",
            ),
        ]
        indexes = [
            models.Index(
                fields=["service", "environment"], name="ix_service_credentials_svc"
            ),
        ]

    def __str__(self) -> str:
        # Never the secret, never the id: the admin and the logs print this.
        return f"{self.service.code}:{self.environment}:{self.label or self.pk}"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        bad = [
            key
            for key in (self.extra or {})
            if any(word in str(key).lower() for word in _FORBIDDEN_EXTRA_WORDS)
        ]
        if bad:
            raise ValidationError(
                {"extra": f"extra is for settings that are not secret; remove: {', '.join(bad)}"}
            )

    def save(self, *args, **kwargs) -> None:
        secret = self.app_secret or ""
        self.secret_hint = secret[-4:] if len(secret) >= 12 else ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "app_secret" in update_fields:
            kwargs["update_fields"] = {*update_fields, "secret_hint"}
        super().save(*args, **kwargs)
