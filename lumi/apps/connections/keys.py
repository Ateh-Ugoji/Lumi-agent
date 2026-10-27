"""Registration of the connections services in ``apps.core.keys`` (the ``check_keys`` registry).

Probes make at most one free, read-only call. X is never probed: every X call spends prepaid
credits, so its probe only reports that it was skipped.
"""

from __future__ import annotations

import asyncio
import os

from apps.core import keys

from .config import ConnectionsConfig
from .errors import SocialDataError
from .providers.registry import build_provider


def _config() -> ConnectionsConfig:
    return ConnectionsConfig.from_env(os.environ)


def probe_meta() -> keys.ProbeResult:
    try:
        provider = build_provider("meta", _config())
        asyncio.run(provider.check_app_credentials())  # type: ignore[attr-defined]
    except SocialDataError as exc:
        return keys.ProbeResult("failed", f"Meta rechazó la app ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - never include the message, it may echo input
        return keys.ProbeResult("failed", f"sonda de Meta falló ({type(exc).__name__})")
    return keys.ProbeResult(
        "ok", "token de app obtenido con META_APP_ID y META_APP_SECRET"
    )


def probe_linkedin() -> keys.ProbeResult:
    return keys.ProbeResult(
        "skipped",
        "LinkedIn no tiene una prueba sin usuario; se valida al conectar una cuenta",
    )


def probe_x() -> keys.ProbeResult:
    return keys.ProbeResult(
        "skipped",
        "X no se sonda: cada llamada gasta créditos prepagados",
    )


SPECS: tuple[keys.KeySpec, ...] = (
    keys.KeySpec(
        name="meta",
        variables=("META_APP_ID", "META_APP_SECRET"),
        probe=probe_meta,
        description="Meta (Facebook Pages): login y publicación",
        secret_variables=("META_APP_SECRET",),
    ),
    keys.KeySpec(
        name="linkedin",
        variables=("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
        probe=probe_linkedin,
        description="LinkedIn: login y publicación",
        secret_variables=("LINKEDIN_CLIENT_SECRET",),
    ),
    keys.KeySpec(
        name="x",
        variables=("X_CLIENT_ID", "X_CLIENT_SECRET"),
        probe=probe_x,
        description="X: login y publicación (apagado con X_LIVE_ENABLED=false)",
        secret_variables=("X_CLIENT_SECRET",),
    ),
)


def register_all() -> None:
    for spec in SPECS:
        keys.register(spec)
