"""``POST /connections/{provider}/link``: pick which connected account publishes for a profile.

A Meta login with several Pages stores every Page and links none. The user picks one per
profile here. See docs/CONTRATOS.md section 4.1.

The account is the user's own (``user`` is part of the lookup, so a foreign id is a 404 and
never a 403). Everything runs under row locks in one transaction: the profile row first, then
the affected account rows in ``id`` order, so two links cannot deadlock or break the partial
unique index on (``social_profile``, ``provider``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.db.models import Q

from apps.core.errors import ApiError
from apps.profiles.models import SocialProfile

from . import accounts
from .models import AccountStatus, ConnectedAccount

#: Google is a user-level grant for the MCP tools. It belongs to no profile.
LINKABLE = ("pfm", "meta", "linkedin", "x")
_UNUSABLE = (AccountStatus.REVOKED, AccountStatus.ERROR)


def ensure_linkable(provider: str) -> None:
    accounts.require_provider(provider)  # unknown provider: the same 404 as every route
    if provider not in LINKABLE:
        raise ApiError(
            "connections.unsupported",
            "Este proveedor no enlaza cuentas a perfiles.",
            status_code=400,
        )


def link_account(user, provider: str, *, account_id: str, profile) -> dict[str, Any]:
    ensure_linkable(provider)
    with transaction.atomic():
        # Serialise every link on this profile before touching an account.
        locked = SocialProfile.objects.select_for_update().get(pk=profile.pk)
        rows = list(
            ConnectedAccount.objects.filter(user=user, provider=provider)
            .filter(Q(external_account_id=account_id) | Q(social_profile_id=locked.pk))
            .defer(*accounts.TOKEN_COLUMNS)
            .order_by("pk")
            .select_for_update()
        )
        target = next((r for r in rows if r.external_account_id == account_id), None)
        if target is None:
            raise ApiError("not_found", "No encontrado.", status_code=404)
        if target.status in _UNUSABLE:
            raise ApiError(
                "connections.account_unusable",
                "La cuenta necesita reconectarse antes de enlazarla.",
                status_code=409,
                details={"provider": provider, "status": target.status},
            )
        wanted = profile.handle.platform
        if target.platform and target.platform != wanted:
            raise ApiError(
                "connections.platform_mismatch",
                "La cuenta es de otra red social que el perfil.",
                status_code=409,
                details={
                    "account_platform": target.platform,
                    "profile_platform": wanted,
                },
            )
        if target.social_profile_id == locked.pk:
            return _body(provider, locked.pk, target, None, None)
        replaced = next(
            (r for r in rows if r.social_profile_id == locked.pk and r.pk != target.pk),
            None,
        )
        moved_from = target.social_profile_id
        now = datetime.now(UTC)
        if replaced is not None:
            # First: the unique index allows one account per (profile, provider).
            ConnectedAccount.objects.filter(pk=replaced.pk).update(
                social_profile=None, updated_at=now
            )
        ConnectedAccount.objects.filter(pk=target.pk).update(
            social_profile=locked, updated_at=now
        )
        target.social_profile_id = locked.pk
        return _body(
            provider,
            locked.pk,
            target,
            replaced.external_account_id if replaced else None,
            moved_from,
        )


def _body(provider, profile_id, account, replaced_id, moved_from) -> dict[str, Any]:
    return {
        "provider": provider,
        "profile_id": profile_id,
        "account": account,
        "replaced_account_id": replaced_id,
        "moved_from_profile_id": moved_from,
    }
