"""T8 importers for the legacy tables CONNECT owns (CONTRATOS section 10, order 200 to 299).

* ``mcp_auth_accounts``: the legacy table held one global row per account. Each row becomes the
  imported user's ``McpAuthAccount``. Tokens are encrypted by ``EncryptedTextField`` on save.
* ``profiles.pfm_account_id``: becomes one ``connected_accounts`` row with provider ``pfm``,
  linked to the surviving ``social_profile``. A missing id, or one that starts with ``demo-``,
  creates nothing. The id stays in ``external_account_id`` (plain, it is the unique key PFM calls
  use; PFM holds the real credentials). It is not a token and no other column copies it.

Neither the tokens nor the Post for Me ids reach a log, a warning or the report: warnings name
only the legacy table and row id.
"""

from __future__ import annotations

from apps.connections.models import (
    AccountStatus,
    ConnectedAccount,
    McpAuthAccount,
    Provider,
)
from apps.core.legacy_import import ImportContext, Importer, register, to_dt
from apps.profiles.legacy_import import profile_targets
from apps.profiles.models import SocialHandle

DEMO_PREFIX = "demo-"
MAX_ACCOUNT = 40
MAX_EXTERNAL_ID = 128


def _scopes(value: object) -> list[str]:
    return str(value or "").replace(",", " ").split()


def import_mcp_auth_accounts(ctx: ImportContext) -> None:
    report = ctx.table("mcp_auth_accounts")
    for row in ctx.legacy.rows("mcp_auth_accounts"):
        report.read += 1
        legacy_id = row["id"]
        if ctx.is_done("mcp_auth_accounts", legacy_id, "mcp_auth_accounts"):
            report.already += 1
            continue
        account = str(row.get("account") or "").strip().lower()
        access = row.get("access_token") or ""
        if not account or len(account) > MAX_ACCOUNT:
            ctx.skip("mcp_auth_accounts", legacy_id, "cuenta sin nombre válido")
            continue
        if not access:
            ctx.skip("mcp_auth_accounts", legacy_id, "sin access token")
            continue
        values = {
            "access_token": access,
            "refresh_token": row.get("refresh_token") or "",
            "token_type": row.get("token_type") or "Bearer",
            "scopes": _scopes(row.get("scopes")),
            "expires_at": to_dt(row.get("expires_at")),
        }
        obj, created = McpAuthAccount.objects.update_or_create(
            user=ctx.user, account=account, defaults=values
        )
        ctx.remember("mcp_auth_accounts", legacy_id, "mcp_auth_accounts", obj.pk)
        if created:
            report.imported += 1
        else:
            report.merged += 1


def import_pfm_accounts(ctx: ImportContext) -> None:
    report = ctx.table("connected_accounts")
    targets = profile_targets(ctx)
    handles = {
        h.pk: h
        for h in SocialHandle.objects.filter(pk__in={h for _, h in targets.values()})
    }
    for row in ctx.legacy.rows("profiles"):
        external_id = str(row.get("pfm_account_id") or "").strip()
        if not external_id:
            continue
        report.read += 1
        legacy_id = row["id"]
        if external_id.lower().startswith(DEMO_PREFIX):
            report.skipped += 1
            continue
        if ctx.is_done("profiles", legacy_id, "connected_accounts"):
            report.already += 1
            continue
        target = targets.get(int(legacy_id))
        if target is None or len(external_id) > MAX_EXTERNAL_ID:
            report.skipped += 1
            ctx.warn(
                f"profiles {legacy_id}: sin perfil destino, no se crea la cuenta pfm"
            )
            continue
        profile_id, handle_id = target
        handle = handles[handle_id]
        taken = ConnectedAccount.objects.filter(provider=Provider.PFM).filter(
            external_account_id=external_id
        ) | ConnectedAccount.objects.filter(
            provider=Provider.PFM, social_profile_id=profile_id
        )
        if taken.exists():
            existing = taken.first()
            if existing.social_profile_id == profile_id and (
                existing.external_account_id == external_id
            ):
                ctx.remember("profiles", legacy_id, "connected_accounts", existing.pk)
                report.already += 1
            else:
                report.skipped += 1
                ctx.warn(
                    f"profiles {legacy_id}: el perfil destino ya tiene una cuenta pfm, "
                    "no se crea otra"
                )
            continue
        account = ConnectedAccount.objects.create(
            user=ctx.user,
            social_profile_id=profile_id,
            provider=Provider.PFM,
            external_account_id=external_id,
            platform=handle.platform,
            display_name=handle.display_name or row.get("name") or "",
            handle=handle.handle_display or handle.handle_normalized,
            status=AccountStatus.ACTIVE,
        )
        ctx.remember("profiles", legacy_id, "connected_accounts", account.pk)
        report.imported += 1


register(
    Importer(
        name="connections.mcp_auth_accounts",
        tables=("mcp_auth_accounts",),
        order=200,
        run=import_mcp_auth_accounts,
    )
)
register(
    Importer(
        name="connections.pfm_accounts",
        tables=(),
        order=210,
        run=import_pfm_accounts,
    )
)
