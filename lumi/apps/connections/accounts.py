"""Connected-account service: connect, callback, status, disconnect and token refresh.

This is Django glue. The OAuth rules live in the pure ``OAuthFlow``; this module stores the
result in ``connected_accounts`` and maps provider errors to the API error format.

Tokens never leave this module in plain text except into a provider call. Serializers read
only the public columns.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from asgiref.sync import async_to_sync
from django.db import IntegrityError, connection, transaction

from apps.core.errors import ApiError
from apps.core.fields import TokenDecryptError, decrypt_value
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
from .mcp.google import GoogleOAuth
from .models import (
    AccountStatus,
    ConnectedAccount,
    McpAuthAccount,
    McpPendingWrite,
    PfmLink,
    Provider,
)
from .oauth import OAuthFlow, OAuthProvider
from .providers.base import AccountInfo, SocialProvider, TokenSet
from .providers.registry import build_provider
from .stores import DjangoOAuthStateStore, save_google_tokens

logger = logging.getLogger(__name__)

OAUTH_PROVIDERS = (Provider.META, Provider.LINKEDIN, Provider.X)
ALL_PROVIDERS = tuple(p.value for p in Provider)
REFRESH_WINDOW = timedelta(days=7)

# Variables each provider needs before its connect flow can start.
REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "pfm": ("PFM_JWT_TOKEN",),
    "meta": ("META_APP_ID", "META_APP_SECRET"),
    "linkedin": ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
    "x": ("X_CLIENT_ID", "X_CLIENT_SECRET"),
    "google": ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"),
}
_CONFIG_ATTR = {
    "PFM_JWT_TOKEN": "pfm_jwt_token",
    "META_APP_ID": "meta_app_id",
    "META_APP_SECRET": "meta_app_secret",
    "LINKEDIN_CLIENT_ID": "linkedin_client_id",
    "LINKEDIN_CLIENT_SECRET": "linkedin_client_secret",
    "X_CLIENT_ID": "x_client_id",
    "X_CLIENT_SECRET": "x_client_secret",
    "GOOGLE_OAUTH_CLIENT_ID": "google_client_id",
    "GOOGLE_OAUTH_CLIENT_SECRET": "google_client_secret",
}


def get_config() -> ConnectionsConfig:
    return ConnectionsConfig.from_env(os.environ)


def make_provider(name: str) -> SocialProvider:
    """Build a provider. Tests replace this to inject a mock transport."""
    return build_provider(name, get_config())


def make_google() -> GoogleOAuth:
    """Build the Google OAuth client. Tests replace this to inject a mock transport."""
    return GoogleOAuth(get_config())


def oauth_provider(name: str) -> OAuthProvider:
    return make_google() if name == "google" else make_provider(name)


def make_pfm() -> PfmClient:
    """Build the PFM client. Tests replace this to inject a mock transport."""
    return PfmClient(get_config())


def legacy_pfm_external_id(user_id: int) -> str:
    """The guessable id Lumi used before ``PfmLink``. Kept only for users that already have it."""
    return f"lumi-user-{user_id}"


def pfm_external_id(user, *, create: bool = False) -> str | None:
    """The external id Lumi gave PFM for ``user``. One per user, so PFM refuses an account that is
    already tied to another Lumi user.

    ``create`` mints a random one for a user who has none. Without it, a user with no link and no
    PFM account gets ``None`` and nothing is asked of PFM. A user who already has PFM rows but no
    link (created before the table) keeps the legacy id.
    """
    link = PfmLink.objects.filter(user=user).first()
    if link is not None:
        return link.external_id
    legacy = ConnectedAccount.objects.filter(user=user, provider="pfm").exists()
    if not (create or legacy):
        return None
    value = (
        legacy_pfm_external_id(user.pk)
        if legacy
        else f"lumi-{secrets.token_urlsafe(18)}"
    )
    link, _ = PfmLink.objects.get_or_create(user=user, defaults={"external_id": value})
    return link.external_id


def missing_env(provider: str, config: ConnectionsConfig) -> list[str]:
    return [
        name
        for name in REQUIRED_ENV.get(provider, ())
        if not getattr(config, _CONFIG_ATTR[name])
    ]


def require_provider(name: str) -> str:
    if name not in ALL_PROVIDERS:
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
                platform, pfm_external_id(user, create=True)
            )
            return auth.url
        flow = OAuthFlow(
            oauth_provider(provider),
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


def ensure_callback_provider(provider: str) -> None:
    """404 for an unknown provider and 400 ``unsupported`` for Post for Me, which has no state."""
    require_provider(provider)
    if provider == "pfm":
        raise ApiError(
            "connections.unsupported", "Post for Me no usa este paso.", status_code=400
        )


def complete_connect(
    user, provider: str, *, state: str, code: str = "", error: str = ""
) -> dict[str, Any]:
    """Finish a grant for the LOGGED-IN user. The state must have been started by that user.

    The provider sends the browser to a frontend page, which posts ``code`` and ``state`` here
    with the user's Token. A state that belongs to someone else answers 409 ``state_mismatch``
    and stays unused, so its owner can still finish. ``error`` is what the provider put in its
    redirect when the user said no: the state is burned and the answer is 400.
    """
    ensure_callback_provider(provider)
    config = get_config()
    store = DjangoOAuthStateStore(config.redirect_uri)
    try:
        if error or not code:
            async_to_sync(store.consume)(state, provider, user_id=user.pk)
            raise ApiError(
                "connections.access_denied" if error else "connections.state_invalid",
                "La conexión se canceló. Empieza de nuevo.",
                status_code=400,
            )
        flow = OAuthFlow(oauth_provider(provider), store, config)
        done = async_to_sync(flow.complete)(
            state=state, code=code, expected_user_id=user.pk
        )
        count = store_accounts(
            provider,
            user_id=int(done.record.user_id),
            tokens=done.tokens,
            profile_id=done.record.profile_id,
        )
        if count == 0:
            raise ApiError(
                "connections.no_accounts",
                "La autorización no incluyó ninguna cuenta.",
                status_code=422,
            )
        return {
            "provider": provider,
            "connected": True,
            "accounts": count,
            "redirect_after": done.record.redirect_after,
        }
    except OAuthStateError as exc:
        mismatch = exc.code == "state_mismatch"
        raise ApiError(
            f"connections.{exc.code}",
            "Ese enlace de conexión lo empezó otro usuario."
            if mismatch
            else "El enlace de conexión no es válido o caducó. Empieza de nuevo.",
            status_code=409 if mismatch else 400,
        ) from exc
    except AccountTaken as exc:
        raise ApiError(
            "connections.account_taken",
            "Esa cuenta ya está conectada a otro usuario de Lumi.",
            status_code=409,
        ) from exc
    except (SocialDataError, ApiError) as exc:
        raise api_error_from(exc) from exc


class AccountTaken(Exception):
    """The provider account already belongs to another Lumi user."""


def store_accounts(
    provider: str, *, user_id: int, tokens: TokenSet, profile_id: int | None
) -> int:
    """Save every account the grant gives access to. Returns how many were stored."""
    if provider == "google":
        # One Google grant per user. It is not tied to a social profile.
        save_google_tokens(user_id, tokens)
        return 1
    adapter = make_provider(provider)
    infos = async_to_sync(adapter.list_accounts)(tokens)
    if not infos:
        return 0
    link = profile_id if len(infos) == 1 else None
    with transaction.atomic():
        for info in infos:
            _upsert(provider, adapter, user_id, info, tokens, link)
    return len(infos)


def _lock_account(provider: str, external_id: str, user_id: int) -> ConnectedAccount:
    """The row for (provider, external id), locked, created first when it is missing.

    Two requests can race to create the same account (React renders twice, a double click on
    the callback). The loser of the unique index hits ``IntegrityError`` in its own savepoint
    and reads the winner's row instead of failing with a 500.
    """
    rows = (
        ConnectedAccount.objects.select_for_update()
        .defer(*TOKEN_COLUMNS)
        .filter(provider=provider, external_account_id=external_id)
    )
    row = rows.first()
    if row is None:
        try:
            with transaction.atomic():
                ConnectedAccount.objects.create(
                    user_id=user_id, provider=provider, external_account_id=external_id
                )
        except IntegrityError:
            pass
        row = rows.get()
    return row


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
    row = _lock_account(provider, info.external_id, user_id)
    if row.user_id != user_id:
        raise AccountTaken
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


# --- unreadable tokens --------------------------------------------------------

#: Loading a row decrypts these. After a key change they can fail, so any code that does not need
#: a token reads the row without them, and one bad row never takes a whole request down.
TOKEN_COLUMNS = ("access_token", "refresh_token")
UNREADABLE = "TokenDecryptError"
_LIVE_STATUSES = (AccountStatus.ACTIVE, AccountStatus.LIMITED)


def quarantine_unreadable(
    *, user_id: int | None = None, provider: str | None = None
) -> int:
    """Mark live accounts whose tokens no configured key opens as ``error``, so the user can
    connect them again. Reads the ciphertext straight from the table: nothing is decrypted into
    the model, and no value is logged. Returns how many rows were marked."""
    table = ConnectedAccount._meta.db_table
    sql = f"SELECT id, access_token, refresh_token FROM {table} WHERE status = ANY(%s)"
    params: list = [[str(s) for s in _LIVE_STATUSES]]
    if user_id is not None:
        sql += " AND user_id = %s"
        params.append(user_id)
    if provider is not None:
        sql += " AND provider = %s"
        params.append(provider)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    bad: list[int] = []
    for pk, access, refresh in rows:
        try:
            for value in (access, refresh):
                if value:
                    decrypt_value(value)
        except TokenDecryptError:
            bad.append(pk)
    if not bad:
        return 0
    logger.warning("%d connected account(s) hold tokens no key opens", len(bad))
    return ConnectedAccount.objects.filter(
        pk__in=bad, status__in=_LIVE_STATUSES
    ).update(
        status=AccountStatus.ERROR, last_error=UNREADABLE, updated_at=datetime.now(UTC)
    )


# --- status ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    configured: bool
    connected: bool
    stale: bool
    accounts: list[ConnectedAccount]
    # Provider-specific facts that are not accounts (Google's grant). Never a token.
    details: dict = field(default_factory=dict)


def _google_status(user, configured: bool) -> ProviderStatus:
    try:
        row = McpAuthAccount.objects.filter(user=user, account="google").first()
    except TokenDecryptError:
        logger.warning("google grant of a user is unreadable")
        return ProviderStatus(
            "google", configured, False, False, [], {"unreadable": True}
        )
    if row is None or not row.access_token:
        return ProviderStatus("google", configured, False, False, [], {})
    expired = row.expires_at is not None and row.expires_at <= datetime.now(UTC)
    has_refresh = bool(row.refresh_token)
    # Without a refresh token the grant dies with the access token (about an hour).
    stale = expired and not has_refresh
    return ProviderStatus(
        "google",
        configured,
        not stale,
        stale,
        [],
        {
            "scopes": list(row.scopes),
            "expires_at": row.expires_at,
            "has_refresh_token": has_refresh,
        },
    )


def provider_status(user, provider: str) -> ProviderStatus:
    require_provider(provider)
    config = get_config()
    configured = not missing_env(provider, config)
    if provider == "google":
        return _google_status(user, configured)
    stale = False
    if provider == "pfm" and configured:
        try:
            sync_pfm_accounts(user)
        except SocialDataError:
            stale = True
    quarantine_unreadable(user_id=user.pk, provider=provider)
    accounts = list(
        ConnectedAccount.objects.filter(user=user, provider=provider)
        .defer(*TOKEN_COLUMNS)
        .select_related("social_profile")
        .order_by("id")
    )
    connected = any(
        a.status in (AccountStatus.ACTIVE, AccountStatus.LIMITED) for a in accounts
    )
    return ProviderStatus(provider, configured, connected, stale, accounts)


PFM_PAGE_SIZE = 50
PFM_MAX_PAGES = 20


def _list_pfm_accounts(external_id: str) -> list:
    """Every account PFM lists for ``external_id``, page by page. The filter is the remote's job,
    so each row is checked again here. A row under another id is dropped."""
    client = make_pfm()
    found: list = []
    for page in range(PFM_MAX_PAGES):
        batch = async_to_sync(client.list_social_accounts)(
            limit=PFM_PAGE_SIZE,
            offset=page * PFM_PAGE_SIZE,
            external_id=external_id,
        )
        found.extend(a for a in batch if a.external_id == external_id)
        if len(batch) < PFM_PAGE_SIZE:
            return found
    raise ProviderUnavailable("PFM account list is too long", provider="pfm")


def sync_pfm_accounts(user) -> int:
    """Mirror the user's PFM accounts into ``connected_accounts``. PFM holds the tokens.

    Only accounts that PFM reports under the user's own ``external_id`` are attached, and a
    partial list never revokes anything.
    """
    external_id = pfm_external_id(user)
    if external_id is None:
        return 0
    remote = _list_pfm_accounts(external_id)
    seen: set[str] = set()
    with transaction.atomic():
        for acc in remote:
            seen.add(acc.id)
            row = _lock_account("pfm", acc.id, user.pk)
            if row.user_id != user.pk:
                continue
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
    if provider == "google":
        return _disconnect_google(user)
    rows = ConnectedAccount.objects.filter(user=user, provider=provider)
    if account_id:
        rows = rows.filter(external_account_id=account_id)
        if not rows.exists():
            raise ApiError("not_found", "Cuenta no encontrada.", status_code=404)
    revoked = 0
    deleted = 0
    for row in list(rows.defer(*TOKEN_COLUMNS)):
        if _revoke_remote(provider, row):
            revoked += 1
        row.delete()
        deleted += 1
    return {"provider": provider, "disconnected": deleted, "remote_revoked": revoked}


def _disconnect_google(user) -> dict:
    """Revoke the grant at Google (best effort), then delete the tokens and parked writes."""
    row = McpAuthAccount.objects.filter(user=user, account="google").first()
    if row is None:
        return {"provider": "google", "disconnected": 0, "remote_revoked": 0}
    revoked = 0
    try:
        tokens = TokenSet(
            access_token=row.access_token, refresh_token=row.refresh_token or None
        )
        if async_to_sync(make_google().revoke)(tokens).remote_revoked:
            revoked = 1
    except SocialDataError:
        logger.warning("remote revoke failed for google", exc_info=False)
    with transaction.atomic():
        McpPendingWrite.objects.filter(user=user).delete()
        row.delete()
    return {"provider": "google", "disconnected": 1, "remote_revoked": revoked}


def _revoke_remote(provider: str, row: ConnectedAccount) -> bool:
    try:
        if provider == "pfm":
            async_to_sync(make_pfm().disconnect_social_account)(row.external_account_id)
            return True
        outcome = async_to_sync(make_provider(provider).revoke)(token_set(row))
        return bool(outcome.remote_revoked)
    except TokenDecryptError:
        # Nothing to revoke with. The user still gets out: the rows are deleted by the caller.
        logger.warning("tokens unreadable, remote revoke skipped for %s", provider)
        return False
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
            .defer(*TOKEN_COLUMNS)
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
        try:
            tokens = token_set(row)
        except TokenDecryptError:
            # One unreadable row must not stop the others. The user connects it again.
            row.status = AccountStatus.ERROR
            row.last_error = UNREADABLE
            row.save(update_fields=["status", "last_error", "updated_at"])
            return "unreadable"
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
