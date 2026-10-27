"""Connected-account service: connect, callback, status, disconnect and token refresh.

This is Django glue. The OAuth rules live in the pure ``OAuthFlow``; this module stores the
result in ``connected_accounts`` and maps provider errors to the API error format.

Tokens never leave this module in plain text except into a provider call. Serializers read
only the public columns.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from asgiref.sync import async_to_sync
from django.db import transaction

from apps.core.errors import ApiError
from apps.core.permissions import get_owned_profile

from .clients.pfm import PfmClient
from .config import ConnectionsConfig
from .errors import (
    LiveDisabled,
    OAuthStateError,
    ProviderAuthError,
    ProviderUnavailable,
    RateLimited,
    SocialDataError,
    UnsupportedOperation,
    ValidationFailed,
)
from .models import AccountStatus, ConnectedAccount, Provider
from .oauth import OAuthFlow
from .providers.base import AccountInfo, SocialProvider, TokenSet
from .providers.registry import build_provider
from .stores import DjangoOAuthStateStore

logger = logging.getLogger(__name__)

OAUTH_PROVIDERS = (Provider.META, Provider.LINKEDIN, Provider.X)
ALL_PROVIDERS = (*(p.value for p in Provider), "google")
REFRESH_WINDOW = timedelta(days=7)

# Variables each provider needs before its connect flow can start.
REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "pfm": ("PFM_JWT_TOKEN",),
    "meta": ("META_APP_ID", "META_APP_SECRET"),
    "linkedin": ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
    "x": ("X_CLIENT_ID", "X_CLIENT_SECRET"),
}
_CONFIG_ATTR = {
    "PFM_JWT_TOKEN": "pfm_jwt_token",
    "META_APP_ID": "meta_app_id",
    "META_APP_SECRET": "meta_app_secret",
    "LINKEDIN_CLIENT_ID": "linkedin_client_id",
    "LINKEDIN_CLIENT_SECRET": "linkedin_client_secret",
    "X_CLIENT_ID": "x_client_id",
    "X_CLIENT_SECRET": "x_client_secret",
}


def get_config() -> ConnectionsConfig:
    return ConnectionsConfig.from_env(os.environ)


def make_provider(name: str) -> SocialProvider:
    """Build a provider. Tests replace this to inject a mock transport."""
    return build_provider(name, get_config())


def make_pfm() -> PfmClient:
    """Build the PFM client. Tests replace this to inject a mock transport."""
    return PfmClient(get_config())


def pfm_external_id(user_id: int) -> str:
    """The external id Lumi gives PFM. One per user, so PFM refuses an account that is
    already tied to another Lumi user."""
    return f"lumi-user-{user_id}"


def missing_env(provider: str, config: ConnectionsConfig) -> list[str]:
    return [
        name
        for name in REQUIRED_ENV.get(provider, ())
        if not getattr(config, _CONFIG_ATTR[name])
    ]


def require_provider(name: str) -> str:
    if name == "google":
        raise ApiError(
            "connections.not_implemented",
            "Google se conecta por MCP y todavía no está disponible.",
            status_code=501,
        )
    if name not in {p.value for p in Provider}:
        raise ApiError("not_found", "Proveedor desconocido.", status_code=404)
    return name


def api_error_from(exc: Exception) -> ApiError:
    """Translate a provider failure. The message is generic: provider bodies never reach clients."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, LiveDisabled):
        return ApiError(
            "connections.live_disabled",
            "Este proveedor está apagado en este entorno.",
            status_code=409,
        )
    if isinstance(exc, ProviderAuthError):
        return ApiError(
            "connections.provider_rejected",
            "El proveedor rechazó las credenciales. Vuelve a conectar la cuenta.",
            status_code=502,
        )
    if isinstance(exc, RateLimited):
        return ApiError(
            "rate_limited",
            "El proveedor pide esperar antes de reintentar.",
            status_code=429,
        )
    if isinstance(exc, ValidationFailed):
        return ApiError("validation_error", "Datos no válidos para el proveedor.")
    if isinstance(exc, UnsupportedOperation):
        return ApiError(
            "connections.unsupported", "El proveedor no admite esta acción."
        )
    if isinstance(exc, (ProviderUnavailable, SocialDataError)):
        return ApiError(
            "upstream_error", "El proveedor no responde ahora.", status_code=502
        )
    raise exc


# --- connect -----------------------------------------------------------------


def start_connect(
    user,
    provider: str,
    *,
    redirect_after: str | None = None,
    profile_id: int | None = None,
    platform: str | None = None,
) -> str:
    """Return the URL the browser must open. Nothing is stored for PFM."""
    require_provider(provider)
    config = get_config()
    missing = missing_env(provider, config)
    if missing:
        raise ApiError(
            "not_configured",
            "Faltan credenciales de la aplicación para este proveedor.",
            status_code=503,
            details={"env_vars": missing},
        )
    if provider == "x" and not config.x_live_enabled:
        raise ApiError(
            "connections.live_disabled",
            "X está apagado en este entorno (X_LIVE_ENABLED=false).",
            status_code=409,
            details={"env_vars": ["X_LIVE_ENABLED"]},
        )
    if profile_id is not None:
        get_owned_profile(user, profile_id)  # 404 when it is not the caller's
    try:
        if provider == "pfm":
            if not platform:
                raise ApiError(
                    "validation_error",
                    "Indica la red social en `platform`.",
                    details={"platform": "required"},
                )
            auth = async_to_sync(make_pfm().create_auth_url)(
                platform, pfm_external_id(user.pk)
            )
            return auth.url
        flow = OAuthFlow(
            make_provider(provider),
            DjangoOAuthStateStore(config.redirect_uri),
            config,
        )
        request = async_to_sync(flow.start)(
            user.pk, redirect_after, profile_id=profile_id
        )
        return request.url
    except Exception as exc:
        raise api_error_from(exc) from exc


# --- callback ----------------------------------------------------------------


def frontend_redirect(
    config: ConnectionsConfig, target: str | None, **query: str
) -> str:
    """Build the 302 target on the frontend and add ``query`` to it."""
    base = urljoin(config.frontend_url + "/", (target or "/").lstrip("/"))
    parts = urlsplit(base)
    merged = [*parse_qsl(parts.query), *query.items()]
    return urlunsplit(parts._replace(query=urlencode(merged)))


def finish_callback(provider: str, params: Mapping[str, str]) -> str:
    """Handle the provider's redirect back and return where to send the browser.

    Never raises: every failure becomes ``?error=<code>`` on the frontend.
    """
    config = get_config()
    try:
        require_provider(provider)
    except ApiError:
        return frontend_redirect(config, "/", error="connections.unknown_provider")
    if provider == "pfm":
        return _finish_pfm(config, params)
    target = "/"
    try:
        state = params.get("state", "")
        if params.get("error"):
            # The user said no. Burn the state so the link cannot be replayed.
            _burn_state(provider, state)
            return frontend_redirect(config, target, error="connections.access_denied")
        code = params.get("code", "")
        if not code or not state:
            return frontend_redirect(config, target, error="connections.state_invalid")
        flow = OAuthFlow(
            make_provider(provider), DjangoOAuthStateStore(config.redirect_uri), config
        )
        done = async_to_sync(flow.complete)(state=state, code=code)
        target = done.record.redirect_after
        count = store_accounts(
            provider,
            user_id=int(done.record.user_id),
            tokens=done.tokens,
            profile_id=done.record.profile_id,
        )
        if count == 0:
            return frontend_redirect(config, target, error="connections.no_accounts")
        return frontend_redirect(config, target, connected=provider)
    except OAuthStateError as exc:
        return frontend_redirect(config, target, error=f"connections.{exc.code}")
    except AccountTaken:
        return frontend_redirect(config, target, error="connections.account_taken")
    except (SocialDataError, ApiError) as exc:
        return frontend_redirect(config, target, error=api_error_from(exc).api_code)
    except Exception:  # public boundary: a browser redirect must never be a 500
        logger.exception("connections callback failed for %s", provider)
        return frontend_redirect(config, target, error="internal_error")


def _burn_state(provider: str, state: str) -> None:
    if not state:
        return
    store = DjangoOAuthStateStore(get_config().redirect_uri)
    async_to_sync(store.consume)(state, provider)


def _finish_pfm(config: ConnectionsConfig, params: Mapping[str, str]) -> str:
    """PFM keeps its own OAuth. Its redirect carries no Lumi state, so it names no user.

    The accounts are synced by ``GET /connections/pfm/status``, which the frontend calls next.
    """
    if (params.get("isSuccess") or "").lower() == "true":
        return frontend_redirect(config, "/", connected="pfm")
    return frontend_redirect(config, "/", error="connections.pfm_failed")


class AccountTaken(Exception):
    """The provider account already belongs to another Lumi user."""


def store_accounts(
    provider: str, *, user_id: int, tokens: TokenSet, profile_id: int | None
) -> int:
    """Save every account the grant gives access to. Returns how many were stored."""
    adapter = make_provider(provider)
    infos = async_to_sync(adapter.list_accounts)(tokens)
    if not infos:
        return 0
    link = profile_id if len(infos) == 1 else None
    with transaction.atomic():
        for info in infos:
            _upsert(provider, adapter, user_id, info, tokens, link)
    return len(infos)


def _upsert(
    provider: str,
    adapter: SocialProvider,
    user_id: int,
    info: AccountInfo,
    tokens: TokenSet,
    profile_id: int | None,
) -> ConnectedAccount:
    own_token = (
        info.access_token is not None and info.access_token != tokens.access_token
    )
    row = (
        ConnectedAccount.objects.select_for_update()
        .filter(provider=provider, external_account_id=info.external_id)
        .first()
    )
    if row is not None and row.user_id != user_id:
        raise AccountTaken
    if row is None:
        row = ConnectedAccount(
            user_id=user_id, provider=provider, external_account_id=info.external_id
        )
    row.platform = getattr(adapter, "platform", provider)
    row.display_name = info.display_name[:200]
    row.handle = (info.handle or "")[:100]
    row.status = info.status
    row.access_token = info.access_token or tokens.access_token
    row.refresh_token = tokens.refresh_token or ""
    # A Page token carries no expiry of its own.
    row.expires_at = None if own_token else tokens.expires_at
    row.scopes = list(tokens.scopes)
    row.last_refreshed_at = datetime.now(UTC)
    row.last_error = info.note or ""
    if profile_id is not None:
        ConnectedAccount.objects.filter(
            user_id=user_id, provider=provider, social_profile_id=profile_id
        ).exclude(pk=row.pk).update(social_profile=None)
        row.social_profile_id = profile_id
    row.save()
    return row


# --- status ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    configured: bool
    connected: bool
    stale: bool
    accounts: list[ConnectedAccount]


def provider_status(user, provider: str) -> ProviderStatus:
    require_provider(provider)
    config = get_config()
    configured = not missing_env(provider, config)
    stale = False
    if provider == "pfm" and configured:
        try:
            sync_pfm_accounts(user)
        except SocialDataError:
            stale = True
    accounts = list(
        ConnectedAccount.objects.filter(user=user, provider=provider)
        .select_related("social_profile")
        .order_by("id")
    )
    connected = any(
        a.status in (AccountStatus.ACTIVE, AccountStatus.LIMITED) for a in accounts
    )
    return ProviderStatus(provider, configured, connected, stale, accounts)


def sync_pfm_accounts(user) -> int:
    """Mirror the user's PFM accounts into ``connected_accounts``. PFM holds the tokens."""
    remote = async_to_sync(make_pfm().list_social_accounts)(
        external_id=pfm_external_id(user.pk)
    )
    seen: set[str] = set()
    with transaction.atomic():
        for acc in remote:
            seen.add(acc.id)
            row = (
                ConnectedAccount.objects.select_for_update()
                .filter(provider="pfm", external_account_id=acc.id)
                .first()
            )
            if row is not None and row.user_id != user.pk:
                continue
            if row is None:
                row = ConnectedAccount(
                    user=user, provider="pfm", external_account_id=acc.id
                )
            row.platform = acc.platform[:20]
            row.display_name = (acc.username or acc.id)[:200]
            row.handle = (acc.username or "")[:100]
            row.status = (
                AccountStatus.ACTIVE
                if acc.status == "connected"
                else AccountStatus.REVOKED
            )
            row.save()
        ConnectedAccount.objects.filter(user=user, provider="pfm").exclude(
            external_account_id__in=seen
        ).update(status=AccountStatus.REVOKED)
    return len(remote)


# --- disconnect --------------------------------------------------------------


def token_set(row: ConnectedAccount) -> TokenSet:
    return TokenSet(
        access_token=row.access_token,
        refresh_token=row.refresh_token or None,
        expires_at=row.expires_at,
        scopes=tuple(row.scopes),
    )


def disconnect(user, provider: str, *, account_id: str | None = None) -> dict:
    """Revoke at the provider (best effort) and delete the local rows with their tokens."""
    require_provider(provider)
    rows = ConnectedAccount.objects.filter(user=user, provider=provider)
    if account_id:
        rows = rows.filter(external_account_id=account_id)
        if not rows.exists():
            raise ApiError("not_found", "Cuenta no encontrada.", status_code=404)
    revoked = 0
    deleted = 0
    for row in list(rows):
        if _revoke_remote(provider, row):
            revoked += 1
        row.delete()
        deleted += 1
    return {"provider": provider, "disconnected": deleted, "remote_revoked": revoked}


def _revoke_remote(provider: str, row: ConnectedAccount) -> bool:
    try:
        if provider == "pfm":
            async_to_sync(make_pfm().disconnect_social_account)(row.external_account_id)
            return True
        outcome = async_to_sync(make_provider(provider).revoke)(token_set(row))
        return bool(outcome.remote_revoked)
    except SocialDataError:
        # The user wants out. A remote failure must not keep the tokens here.
        logger.warning("remote revoke failed for %s", provider, exc_info=False)
        return False


# --- refresh -----------------------------------------------------------------


def refresh_account(
    account_id: int, *, factory: Callable[[str], SocialProvider] | None = None
) -> str:
    """Refresh one account's tokens. Returns a short outcome word.

    The row stays locked during the provider call because X rotates refresh tokens: two
    workers must not spend the same one.
    """
    factory = factory or make_provider
    with transaction.atomic():
        row = (
            ConnectedAccount.objects.select_for_update(skip_locked=True)
            .filter(pk=account_id)
            .first()
        )
        if row is None:
            return "locked_or_missing"
        if row.provider == "pfm" or row.status in (
            AccountStatus.REVOKED,
            AccountStatus.EXPIRED,
        ):
            return "skipped"
        adapter = factory(row.provider)
        tokens = token_set(row)
        try:
            fresh = async_to_sync(adapter.refresh)(tokens)
        except LiveDisabled:
            return "skipped_live_disabled"
        except (ProviderAuthError, UnsupportedOperation) as exc:
            if tokens.expires_at and tokens.expires_at <= datetime.now(UTC):
                row.status = AccountStatus.EXPIRED
            row.last_error = _reason(exc)
            row.save(update_fields=["status", "last_error", "updated_at"])
            return "needs_reconnect"
        except (RateLimited, ProviderUnavailable) as exc:
            row.last_error = _reason(exc)
            row.save(update_fields=["last_error", "updated_at"])
            return "retry_later"
        row.access_token = fresh.access_token
        if fresh.refresh_token:
            row.refresh_token = fresh.refresh_token
        row.expires_at = fresh.expires_at
        row.last_refreshed_at = datetime.now(UTC)
        row.last_error = ""
        row.save()
        return "refreshed"


def _reason(exc: Exception) -> str:
    return f"{type(exc).__name__}"[:200]


def refresh_due(
    *, window: timedelta = REFRESH_WINDOW, now: datetime | None = None
) -> dict[str, int]:
    """Refresh every active account whose token expires inside ``window``."""
    cutoff = (now or datetime.now(UTC)) + window
    ids = list(
        ConnectedAccount.objects.filter(
            status__in=[AccountStatus.ACTIVE, AccountStatus.LIMITED],
            expires_at__isnull=False,
            expires_at__lte=cutoff,
        )
        .exclude(provider="pfm")
        .values_list("pk", flat=True)
    )
    counts: dict[str, int] = {}
    for pk in ids:
        outcome = refresh_account(pk)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
