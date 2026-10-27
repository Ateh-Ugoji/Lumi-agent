"""Registration of the connections services in ``apps.core.keys`` (the ``check_keys`` registry).

Probes make at most one free, read-only call. PFM lists one connected account (a read).
Xpoz is never called: every call spends credits and no endpoint reports the balance of a key. ``apps.core.keys.run_probe`` runs async probes
and scrubs configured values from the result. X is never probed: every X call spends prepaid
credits, so its probe only reports that it was skipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from apps.core import keys

from .clients.pfm import PfmClient
from .config import ConnectionsConfig
from .errors import ProviderAuthError, SocialDataError
from .providers.registry import build_provider


@dataclass(frozen=True, slots=True)
class Outcome:
    """Shape that ``apps.core.keys`` reads from a probe: ``status`` and ``detail``."""

    status: str
    detail: str = ""


def _config() -> ConnectionsConfig:
    return ConnectionsConfig.from_env(os.environ)


async def probe_meta() -> Outcome:
    try:
        provider = build_provider("meta", _config())
        await provider.check_app_credentials()  # type: ignore[attr-defined]
    except SocialDataError as exc:
        return Outcome("error", f"Meta rechazó la app ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - never include the message, it may echo input
        return Outcome("error", f"sonda de Meta falló ({type(exc).__name__})")
    return Outcome("ok", "token de app obtenido con META_APP_ID y META_APP_SECRET")


def probe_linkedin() -> Outcome:
    return Outcome(
        "skipped",
        "LinkedIn no tiene una prueba sin usuario; se valida al conectar una cuenta",
    )


def probe_x() -> Outcome:
    return Outcome("skipped", "X no se sonda: cada llamada gasta créditos prepagados")


async def probe_pfm() -> Outcome:
    client = PfmClient(_config())
    try:
        await client.list_social_accounts(limit=1)
    except ProviderAuthError:
        return Outcome("error", "PFM rechazó el token (vencido o inválido)")
    except SocialDataError as exc:
        return Outcome("error", f"PFM no respondió bien ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - never include the message
        return Outcome("error", f"sonda de PFM falló ({type(exc).__name__})")
    return Outcome("ok", "PFM aceptó el token (lectura gratuita de cuentas)")


def probe_xpoz() -> Outcome:
    config = _config()
    count = len(config.xpoz_api_keys)
    state = "activadas" if config.xpoz_live_enabled else "desactivadas"
    return Outcome(
        "skipped",
        f"Xpoz no se sonda para no gastar créditos: {count} key(s) cargada(s), "
        f"llamadas en vivo {state} (XPOZ_LIVE_ENABLED), "
        f"tope {config.xpoz_run_credit_budget} créditos por corrida",
    )


def register_all() -> None:
    keys.register("meta", probe_meta, env_vars=("META_APP_ID", "META_APP_SECRET"))
    keys.register(
        "linkedin",
        probe_linkedin,
        env_vars=("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
    )
    keys.register("x", probe_x, env_vars=("X_CLIENT_ID", "X_CLIENT_SECRET"))
    keys.register("pfm", probe_pfm, env_vars=("PFM_JWT_TOKEN",))
    keys.register("xpoz", probe_xpoz, env_vars=("XPOZ_API_KEY",))
