"""Django implementations of the ports the pure core defines.

* ``DjangoOAuthStateStore``: one use per state, claimed by a single ``UPDATE ... RETURNING``.
* ``DjangoPublishLedger``: ``publish_jobs`` rows as the idempotency ledger.
* ``DjangoCreditLedger``: ``xpoz_credit_ledger`` rows.
* ``DjangoHandleStore``: ``handle_search_cache`` plus ``social_handles``.

Each async method runs its blocking ORM work with ``sync_to_async(thread_sensitive=True)``.
The ORM writes to ``social_handles`` directly because ``apps.profiles.services`` is not
published yet. Switch to ``get_or_create_handle`` when it is (docs/CONTRATOS.md section 5).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import IntegrityError, connection, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Now
from django.utils import timezone

from apps.core.fields import TokenDecryptError
from apps.profiles.models import HandleOrigin, SocialHandle, SocialProfile

from .clients.credits import CreditEntry
from .config import ConnectionsConfig
from .errors import BudgetExceeded
from .handles.types import CacheEntry, HandleRow
from .mcp.gateway import PendingWrite
from .models import (
    HandleSearchCache,
    HandleSearchCacheEntry,
    McpAuthAccount,
    McpPendingWrite,
    OAuthState,
    PublishJob,
    PublishStatus,
    XpozCreditLedger,
)
from .oauth import OAuthStateRecord
from .providers.base import PublishResult, TokenSet
from .publishing import LedgerEntry, LedgerStatus, PublishInProgress

_HANDLE_RE = re.compile(r"^[a-z0-9._-]{1,100}$")
_REMEMBERED_LIMIT = 200
# Higher number wins when two sources describe the same handle (SCHEMA section 6.3).
_ORIGIN_WEIGHT = {
    HandleOrigin.SELECTED: 5,
    HandleOrigin.PROFILE: 4,
    HandleOrigin.LIVE: 3,
    HandleOrigin.CACHE: 2,
    HandleOrigin.NICHE: 1,
    HandleOrigin.IMPORT: 0,
}


# --- OAuth state ---------------------------------------------------------------------------

_CONSUME_SQL = """
UPDATE oauth_states
   SET consumed_at = now()
 WHERE state = %s AND provider = %s AND consumed_at IS NULL AND expires_at > now()
RETURNING user_id, provider, code_verifier, redirect_after, expires_at, social_profile_id
"""


class DjangoOAuthStateStore:
    """``redirect_uri_for`` rebuilds the callback URL, which is not stored per state."""

    def __init__(self, redirect_uri_for: Callable[[str], str]) -> None:
        self._redirect_uri_for = redirect_uri_for

    async def save(self, record: OAuthStateRecord) -> None:
        await sync_to_async(self._save, thread_sensitive=True)(record)

    async def consume(self, state: str, provider: str) -> OAuthStateRecord | None:
        return await sync_to_async(self._consume, thread_sensitive=True)(
            state, provider
        )

    def _save(self, record: OAuthStateRecord) -> None:
        OAuthState.objects.create(
            state=record.state,
            user_id=record.user_id,
            provider=record.provider,
            social_profile_id=record.profile_id,
            code_verifier=record.code_verifier or "",
            redirect_after=record.redirect_after,
            expires_at=record.expires_at,
        )

    def _consume(self, state: str, provider: str) -> OAuthStateRecord | None:
        from apps.core.fields import decrypt_value

        with connection.cursor() as cursor:
            cursor.execute(_CONSUME_SQL, [state, provider])
            row = cursor.fetchone()
        if row is None:
            return None
        user_id, found_provider, verifier, redirect_after, expires_at, profile_id = row
        # RETURNING bypasses the field, so the verifier is still ciphertext here.
        return OAuthStateRecord(
            state=state,
            provider=found_provider,
            user_id=user_id,
            redirect_uri=self._redirect_uri_for(found_provider),
            redirect_after=redirect_after,
            expires_at=expires_at,
            code_verifier=decrypt_value(verifier) if verifier else None,
            profile_id=profile_id,
        )


def purge_expired_states() -> int:
    """Delete states that expired or were used. Returns how many rows went."""
    deleted, _ = OAuthState.objects.filter(
        Q(consumed_at__isnull=False) | Q(expires_at__lte=Now())
    ).delete()
    return deleted


# --- Publishing ----------------------------------------------------------------------------


class DjangoPublishLedger:
    """One ledger per request: the request fixes what the ``PublishJob`` row describes."""

    def __init__(
        self,
        *,
        platform: str,
        text: str,
        connected_account_id: int | None = None,
        attempt_id: int | None = None,
    ) -> None:
        self._platform = platform
        self._text = text
        self._account_id = connected_account_id
        self._attempt_id = attempt_id

    async def begin(
        self, scope: int | str, key: str, fingerprint: str
    ) -> tuple[LedgerEntry, bool]:
        return await sync_to_async(self._begin, thread_sensitive=True)(
            int(scope), key, fingerprint
        )

    async def restart(self, scope: int | str, key: str) -> None:
        await sync_to_async(self._restart, thread_sensitive=True)(int(scope), key)

    async def finish(
        self,
        scope: int | str,
        key: str,
        status: LedgerStatus,
        result: PublishResult | None = None,
        error: str = "",
    ) -> None:
        await sync_to_async(self._finish, thread_sensitive=True)(
            int(scope), key, status, result, error
        )

    def _begin(
        self, profile_id: int, key: str, fingerprint: str
    ) -> tuple[LedgerEntry, bool]:
        try:
            with transaction.atomic():
                PublishJob.objects.create(
                    profile_id=profile_id,
                    connected_account_id=self._account_id,
                    attempt_id=self._attempt_id,
                    platform=self._platform,
                    text=self._text,
                    status=PublishStatus.PENDING,
                    fingerprint=fingerprint,
                    idempotency_key=key,
                )
        except IntegrityError:
            job = PublishJob.objects.get(profile_id=profile_id, idempotency_key=key)
            return _entry(job), False
        return LedgerEntry(key=key, fingerprint=fingerprint, status="pending"), True

    def _restart(self, profile_id: int, key: str) -> None:
        moved = PublishJob.objects.filter(
            profile_id=profile_id,
            idempotency_key=key,
            status=PublishStatus.FAILED,
        ).update(status=PublishStatus.PENDING, error="", updated_at=Now())
        if not moved:
            # Another request took the retry first.
            raise PublishInProgress("this post is already being retried")

    def _finish(
        self,
        profile_id: int,
        key: str,
        status: str,
        result: PublishResult | None,
        error: str,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "error": error[:500],
            "updated_at": Now(),
        }
        if result is not None:
            values["external_post_id"] = result.external_post_id or ""
            values["external_url"] = result.url or ""
            values["dry_run"] = result.dry_run
        PublishJob.objects.filter(
            profile_id=profile_id, idempotency_key=key, status=PublishStatus.PENDING
        ).update(**values)


def _entry(job: PublishJob) -> LedgerEntry:
    result = None
    if job.status == PublishStatus.DONE:
        result = PublishResult(
            external_post_id=job.external_post_id or None,
            url=job.external_url or None,
            dry_run=job.dry_run,
        )
    return LedgerEntry(
        key=job.idempotency_key,
        fingerprint=job.fingerprint,
        status=job.status,  # type: ignore[arg-type]
        result=result,
    )


# --- Xpoz credits --------------------------------------------------------------------------


CAP_WINDOW = timedelta(hours=24)


class DjangoCreditLedger:
    """Ledger plus the daily caps. Every paid Xpoz call asks ``ensure_room`` first.

    Two caps apply over a rolling 24 h, both read from ``xpoz_credit_ledger``: one for the
    user and one for everybody. They survive restarts and are shared by every process.
    Two calls that check at the same moment can both pass, so the overshoot is at most one
    call per concurrent request, and the DRF throttle on the routes keeps that small.
    """

    def __init__(self, user_id: int | None = None) -> None:
        self._user_id = user_id

    async def ensure_room(self, credits: int) -> None:
        await sync_to_async(self._ensure_room, thread_sensitive=True)(credits)

    def _ensure_room(self, credits: int) -> None:
        config = ConnectionsConfig.from_env(os.environ)
        since = timezone.now() - CAP_WINDOW
        recent = XpozCreditLedger.objects.filter(created_at__gte=since)
        checks = [(recent, config.xpoz_daily_cap_global, "global")]
        if self._user_id is not None:
            checks.append(
                (
                    recent.filter(user_id=self._user_id),
                    config.xpoz_daily_cap_user,
                    "user",
                )
            )
        for rows, cap, scope in checks:
            spent = rows.aggregate(total=Sum("credits"))["total"] or 0
            if spent + credits > cap:
                raise BudgetExceeded(
                    f"Xpoz daily credit cap reached ({scope})",
                    provider="xpoz",
                    spent=spent,
                    budget=cap,
                )

    async def record(self, entry: CreditEntry) -> None:
        await sync_to_async(self._record, thread_sensitive=True)(entry)

    def _record(self, entry: CreditEntry) -> None:
        XpozCreditLedger.objects.create(
            user_id=self._user_id,
            provider=entry.provider,
            route=entry.route,
            credits=entry.credits,
            key_slot=entry.key_slot,
            run_id=entry.run_id or "",
        )


# --- Handles -------------------------------------------------------------------------------


def normalize_handle(handle: str) -> str | None:
    value = handle.strip().lstrip("@").lower()
    return value if _HANDLE_RE.match(value) else None


def _row(handle: SocialHandle) -> HandleRow:
    return HandleRow(
        handle=handle.handle_display or handle.handle_normalized,
        platform=handle.platform,
        display_name=handle.display_name,
        avatar_url=handle.avatar_url,
        followers=handle.follower_count,
        source="cache",
    )


class DjangoHandleStore:
    """Handle tables over Postgres.

    ``user_id`` limits "handles of profiles already in Lumi" to the caller's own profiles, so
    one user's profile list never leads another user's dropdown. Remembered handles and the
    search cache stay shared: they are public identities and public search results.
    """

    def __init__(self, user_id: int | None = None) -> None:
        self._user_id = user_id

    async def profile_handles(self, platform: str, prefix: str) -> list[str]:
        return await sync_to_async(self._profile_handles, thread_sensitive=True)(
            platform, prefix
        )

    async def remembered(self, platform: str, prefix: str) -> list[HandleRow]:
        return await sync_to_async(self._remembered, thread_sensitive=True)(
            platform, prefix
        )

    async def known_keys(self, platform: str, handles: list[str]) -> set[str]:
        return await sync_to_async(self._known_keys, thread_sensitive=True)(
            platform, handles
        )

    async def related_entries(self, platform: str, query: str) -> list[CacheEntry]:
        return await sync_to_async(self._related_entries, thread_sensitive=True)(
            platform, query
        )

    async def put_entry(self, entry: CacheEntry) -> None:
        await sync_to_async(self._put_entry, thread_sensitive=True)(entry)

    async def remember_live(self, rows: list[HandleRow]) -> None:
        await sync_to_async(self._remember, thread_sensitive=True)(
            rows, HandleOrigin.LIVE, True
        )

    async def remember_new(self, rows: list[HandleRow]) -> None:
        await sync_to_async(self._remember, thread_sensitive=True)(
            rows, HandleOrigin.CACHE, False
        )

    def _profile_handles(self, platform: str, prefix: str) -> list[str]:
        profiles = SocialProfile.objects.filter(
            handle__platform=platform,
            handle__handle_normalized__startswith=prefix.lower(),
        )
        if self._user_id is not None:
            profiles = profiles.filter(user_id=self._user_id)
        names = profiles.values_list("handle__handle_normalized", flat=True).distinct()
        return sorted(names)

    def _remembered(self, platform: str, prefix: str) -> list[HandleRow]:
        qs = SocialHandle.objects.filter(
            platform=platform, handle_normalized__startswith=prefix.lower()
        ).order_by("-follower_count", "handle_normalized")[:_REMEMBERED_LIMIT]
        return [_row(h) for h in qs]

    def _known_keys(self, platform: str, handles: list[str]) -> set[str]:
        wanted = {n for h in handles if (n := normalize_handle(h))}
        found = SocialHandle.objects.filter(
            platform=platform, handle_normalized__in=wanted
        ).values_list("handle_normalized", flat=True)
        return {f"{platform}:{name}" for name in found}

    def _related_entries(self, platform: str, query: str) -> list[CacheEntry]:
        prefixes = [query[:i] for i in range(1, len(query) + 1)]
        caches = (
            HandleSearchCache.objects.filter(platform=platform)
            .filter(
                Q(query_normalized__in=prefixes) | Q(query_normalized__startswith=query)
            )
            .prefetch_related("entries__handle")
        )
        return [
            CacheEntry(
                platform=cache.platform,
                query=cache.query_normalized,
                fetched_at=cache.fetched_at,
                rows=tuple(_row(e.handle) for e in cache.entries.all()),
            )
            for cache in caches
        ]

    def _put_entry(self, entry: CacheEntry) -> None:
        with transaction.atomic():
            cache, _ = HandleSearchCache.objects.update_or_create(
                platform=entry.platform,
                query_normalized=entry.query,
                defaults={"fetched_at": entry.fetched_at},
            )
            cache.entries.all().delete()
            handle_ids = self._ensure_handles(entry.platform, entry.rows)
            HandleSearchCacheEntry.objects.bulk_create(
                [
                    HandleSearchCacheEntry(cache=cache, handle_id=hid, rank=rank)
                    for rank, hid in enumerate(handle_ids)
                ],
                ignore_conflicts=True,
            )

    def _ensure_handles(self, platform: str, rows: Iterable[HandleRow]) -> list[int]:
        """Return the ids of the rows' handles in order, creating the missing ones."""
        names: list[str] = []
        for row in rows:
            name = normalize_handle(row.handle)
            if name and name not in names:
                names.append(name)
        existing = dict(
            SocialHandle.objects.filter(
                platform=platform, handle_normalized__in=names
            ).values_list("handle_normalized", "id")
        )
        missing = [n for n in names if n not in existing]
        if missing:
            SocialHandle.objects.bulk_create(
                [
                    SocialHandle(
                        platform=platform,
                        handle_normalized=n,
                        handle_display=n,
                        origin=HandleOrigin.CACHE,
                    )
                    for n in missing
                ],
                ignore_conflicts=True,
            )
            existing = dict(
                SocialHandle.objects.filter(
                    platform=platform, handle_normalized__in=names
                ).values_list("handle_normalized", "id")
            )
        return [existing[n] for n in names if n in existing]

    def select(self, row: HandleRow) -> str | None:
        """Remember a handle the user picked. Returns the normalized handle, or ``None``."""
        name = normalize_handle(row.handle)
        if name is None:
            return None
        self._remember([row], HandleOrigin.SELECTED, True)
        return name

    def saved(self, platforms: list[str], limit: int) -> list[HandleRow]:
        """Own profile handles first-class, then remembered ones, followers first."""
        rows: dict[str, HandleRow] = {}
        own = SocialProfile.objects.filter(handle__platform__in=platforms)
        if self._user_id is not None:
            own = own.filter(user_id=self._user_id)
        for h in SocialHandle.objects.filter(pk__in=own.values("handle_id")):
            rows[f"{h.platform}:{h.handle_normalized}"] = replace(_row(h), source="db")
        remembered = SocialHandle.objects.filter(platform__in=platforms).order_by(
            F("follower_count").desc(nulls_last=True), "handle_normalized"
        )[:limit]
        for h in remembered:
            rows.setdefault(f"{h.platform}:{h.handle_normalized}", _row(h))
        ordered = sorted(
            rows.values(),
            key=lambda r: (
                r.followers is None,
                -(r.followers or 0),
                r.handle.lower(),
            ),
        )
        return ordered[:limit]

    def counts(self) -> dict[str, int]:
        return {
            "remembered_handles": SocialHandle.objects.count(),
            "cached_searches": HandleSearchCache.objects.count(),
        }

    def _remember(self, rows: list[HandleRow], origin: str, overwrite: bool) -> None:
        by_platform: dict[str, list[HandleRow]] = {}
        for row in rows:
            by_platform.setdefault(row.platform, []).append(row)
        with transaction.atomic():
            for platform, group in by_platform.items():
                self._ensure_handles(platform, group)
                for row in group:
                    name = normalize_handle(row.handle)
                    if name is None:
                        continue
                    current = SocialHandle.objects.get(
                        platform=platform, handle_normalized=name
                    )
                    if not overwrite and not _is_blank(current):
                        continue
                    self._update(current, row, origin)

    def _update(self, current: SocialHandle, row: HandleRow, origin: str) -> None:
        changes: dict[str, object] = {"last_seen_at": Now()}
        if row.handle:
            changes["handle_display"] = row.handle
        if row.display_name:
            changes["display_name"] = row.display_name
        if row.avatar_url:
            changes["avatar_url"] = row.avatar_url
        if row.followers is not None:  # a missing count never wipes a known one
            changes["follower_count"] = row.followers
            changes["follower_count_at"] = Now()
        if _ORIGIN_WEIGHT.get(origin, 0) > _ORIGIN_WEIGHT.get(current.origin, 0):
            changes["origin"] = origin
        SocialHandle.objects.filter(pk=current.pk).update(**changes, updated_at=Now())


def _is_blank(handle: SocialHandle) -> bool:
    """True when nothing but the name is known, so a cache row may fill it in."""
    return (
        not handle.display_name
        and not handle.avatar_url
        and handle.follower_count is None
    )


__all__ = [
    "DjangoCreditLedger",
    "DjangoHandleStore",
    "DjangoOAuthStateStore",
    "DjangoPublishLedger",
    "normalize_handle",
    "purge_expired_states",
]


class DjangoMcpStore:
    """Google tokens in ``mcp_auth_accounts`` and parked writes in ``mcp_pending_writes``."""

    ACCOUNT = "google"

    async def owner_of(self, profile_id: int) -> int | None:
        return await sync_to_async(self._owner_of, thread_sensitive=True)(profile_id)

    async def load_tokens(self, user_id: int) -> TokenSet | None:
        return await sync_to_async(self._load, thread_sensitive=True)(user_id)

    async def save_tokens(self, user_id: int, tokens: TokenSet) -> None:
        await sync_to_async(save_google_tokens, thread_sensitive=True)(user_id, tokens)

    async def park(self, write: PendingWrite) -> PendingWrite | None:
        return await sync_to_async(self._park, thread_sensitive=True)(write)

    async def claim(self, profile_id: int) -> PendingWrite | None:
        return await sync_to_async(self._claim, thread_sensitive=True)(profile_id)

    @staticmethod
    def _owner_of(profile_id: int) -> int | None:
        return (
            SocialProfile.objects.filter(pk=profile_id)
            .values_list("user_id", flat=True)
            .first()
        )

    def _load(self, user_id: int) -> TokenSet | None:
        try:
            row = McpAuthAccount.objects.filter(
                user_id=user_id, account=self.ACCOUNT
            ).first()
        except TokenDecryptError:
            return None  # reads as "not connected"; connecting again replaces it
        if row is None or not row.access_token:
            return None
        return TokenSet(
            access_token=row.access_token,
            refresh_token=row.refresh_token or None,
            expires_at=row.expires_at,
            scopes=tuple(row.scopes),
            token_type=row.token_type or "Bearer",
        )

    @staticmethod
    def _park(write: PendingWrite) -> PendingWrite | None:
        values = {
            "user_id": write.user_id,
            "tool": write.tool,
            "server_tool": write.server_tool,
            "arguments": dict(write.arguments),
            "summary": write.summary,
            "expires_at": write.expires_at,
        }
        with transaction.atomic():
            row, created = McpPendingWrite.objects.select_for_update().get_or_create(
                social_profile_id=write.profile_id, defaults=values
            )
            if created:
                return None
            waiting = _pending_from(row)
            if (
                waiting.expires_at > timezone.now()
                and waiting.confirmation_id != write.confirmation_id
            ):
                return waiting
            for field, value in values.items():
                setattr(row, field, value)
            row.save()
        return None

    @staticmethod
    def _claim(profile_id: int) -> PendingWrite | None:
        with transaction.atomic():
            row = (
                McpPendingWrite.objects.select_for_update(skip_locked=True)
                .filter(social_profile_id=profile_id)
                .first()
            )
            if row is None:
                return None
            write = _pending_from(row)
            row.delete()
        return write


def _pending_from(row: McpPendingWrite) -> PendingWrite:
    return PendingWrite(
        user_id=row.user_id,
        profile_id=row.social_profile_id,
        tool=row.tool,
        server_tool=row.server_tool,
        arguments=row.arguments,
        summary=row.summary,
        expires_at=row.expires_at,
    )


def save_google_tokens(user_id: int, tokens: TokenSet) -> None:
    """Upsert the user's Google grant. A refresh response without a refresh token keeps the old."""
    try:
        existing = McpAuthAccount.objects.filter(
            user_id=user_id, account=DjangoMcpStore.ACCOUNT
        ).first()
    except TokenDecryptError:
        # Nothing in it can be kept. Drop the unreadable grant and write the new one.
        McpAuthAccount.objects.filter(
            user_id=user_id, account=DjangoMcpStore.ACCOUNT
        ).delete()
        existing = None
    refresh = tokens.refresh_token or (existing.refresh_token if existing else "")
    McpAuthAccount.objects.update_or_create(
        user_id=user_id,
        account=DjangoMcpStore.ACCOUNT,
        defaults={
            "access_token": tokens.access_token,
            "refresh_token": refresh or "",
            "token_type": tokens.token_type,
            "scopes": list(tokens.scopes),
            "expires_at": tokens.expires_at,
        },
    )
