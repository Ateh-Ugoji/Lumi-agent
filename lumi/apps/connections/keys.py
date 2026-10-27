"""Registration of the connections services in ``apps.core.keys`` (the ``check_keys`` registry).

Probes make at most one free, read-only call. ``apps.core.keys.run_probe`` runs async probes
and scrubs configured values from the result. X is never probed: every X call spends prepaid
credits, so its probe only reports that it was skipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from apps.core import keys

from .config import ConnectionsConfig
from .errors import SocialDataError
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


def register_all() -> None:
    keys.register("meta", probe_meta, env_vars=("META_APP_ID", "META_APP_SECRET"))
    keys.register(
        "linkedin",
        probe_linkedin,
        env_vars=("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
    )
    keys.register("x", probe_x, env_vars=("X_CLIENT_ID", "X_CLIENT_SECRET"))
