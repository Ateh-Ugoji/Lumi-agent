"""Users and API tokens. See docs/SCHEMA.md section 6.1."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower, Now
from django.utils import timezone

from apps.core.models import TimestampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra):
        email = self.normalize_email(email).lower()
        if not email:
            raise ValueError("El email es obligatorio.")
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create(email, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email=username.strip().lower())


class User(AbstractBaseUser, PermissionsMixin, TimestampedModel):
    email = models.EmailField(max_length=254, unique=True)
    display_name = models.CharField(max_length=120, db_default="", blank=True)
    is_active = models.BooleanField(db_default=True)
    is_staff = models.BooleanField(db_default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="ck_users_email_lowercase",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


def hash_token_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class AuthToken(models.Model):
    """API token. Only the SHA-256 of the key is stored; the key is shown once."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_tokens"
    )
    key_hash = models.CharField(max_length=64)
    name = models.CharField(max_length=80, db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "auth_tokens"
        constraints = [
            models.UniqueConstraint(
                fields=["key_hash"], name="uq_auth_tokens_key_hash"
            ),
        ]

    @classmethod
    def issue(
        cls, user, name: str = "", ttl_days: int | None = None
    ) -> tuple[AuthToken, str]:
        """Create a token and return ``(row, plaintext_key)``. The key cannot be recovered later."""
        key = secrets.token_urlsafe(32)
        days = (
            ttl_days
            if ttl_days is not None
            else getattr(settings, "AUTH_TOKEN_TTL_DAYS", 30)
        )
        row = cls.objects.create(
            user=user,
            key_hash=hash_token_key(key),
            name=name,
            expires_at=timezone.now() + timedelta(days=days),
        )
        return row, key

    @classmethod
    def lookup(cls, key: str) -> AuthToken | None:
        """Return the live token for ``key`` or ``None`` (unknown, expired or inactive user)."""
        row = (
            cls.objects.select_related("user")
            .filter(
                key_hash=hash_token_key(key),
                expires_at__gt=timezone.now(),
                user__is_active=True,
            )
            .first()
        )
        return row
