"""Registry of external services and their keys.

Each app registers its services in ``AppConfig.ready()``::

    from apps.core import keys

    keys.register("groq", probe.run, required=True, env_vars=("GROQ_API_KEY",))

``probe`` is a callable (sync or async) with no arguments that makes one minimal real call and
returns an object with ``status`` (``"ok"``, ``"skipped"`` or ``"error"``), ``detail`` and,
optionally, ``warnings``. ``lumi_ai.ports.ProbeResult`` already has that shape. Probes must never
put a key value in their result; ``run_probe`` scrubs configured values anyway.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger("lumi.keys")

ProbeStatus = Literal["ok", "skipped", "error"]
ProbeCallable = Callable[[], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    status: ProbeStatus
    detail: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KeySpec:
    """One service. ``name`` is the stable id used by ``check_keys --only``.

    Plan names: nombre = name, obligatoria = required, sonda = probe.
    ``env_vars`` must all be set for the service to count as configured.
    """

    name: str
    env_vars: tuple[str, ...]
    required: bool = False
    probe: ProbeCallable | None = None


_REGISTRY: dict[str, KeySpec] = {}


def register(
    name: str,
    probe: ProbeCallable | None = None,
    *,
    required: bool = False,
    env_vars: tuple[str, ...] = (),
) -> KeySpec:
    """Register a service. Registering the same name twice with the same definition is a no-op."""
    spec = KeySpec(name=name, env_vars=tuple(env_vars), required=required, probe=probe)
    existing = _REGISTRY.get(name)
    if existing is not None and (
        existing.env_vars != spec.env_vars or existing.required != spec.required
    ):
        raise ImproperlyConfigured(
            f"El servicio de keys '{name}' ya está registrado con otra definición."
        )
    _REGISTRY[name] = spec
    return spec


def all_specs() -> list[KeySpec]:
    return list(_REGISTRY.values())


def get_spec(name: str) -> KeySpec | None:
    return _REGISTRY.get(name)


def missing_variables(spec: KeySpec) -> list[str]:
    return [var for var in spec.env_vars if not os.environ.get(var, "").strip()]


def missing_required() -> list[str]:
    names: set[str] = set()
    for spec in _REGISTRY.values():
        if spec.required:
            names.update(missing_variables(spec))
    return sorted(names)


def missing_optional() -> dict[str, list[str]]:
    return {
        spec.name: missing_variables(spec)
        for spec in _REGISTRY.values()
        if not spec.required and missing_variables(spec)
    }


def validate_required() -> None:
    """Raise one error that lists every missing required variable."""
    missing = missing_required()
    if missing:
        raise ImproperlyConfigured(
            "Faltan variables obligatorias en lumi/.env: "
            + ", ".join(missing)
            + ". Mira lumi/docs/API_KEYS.md para saber dónde se obtiene cada una."
        )


def warn_optional() -> None:
    """Log one WARNING per missing optional variable. Never logs values."""
    for name, variables in missing_optional().items():
        for variable in variables:
            logger.warning(
                "Servicio opcional '%s' desactivado: falta %s", name, variable
            )


def scrub(text: str) -> str:
    """Remove any configured value of a registered variable from ``text``."""
    cleaned = text
    for spec in _REGISTRY.values():
        for variable in spec.env_vars:
            value = os.environ.get(variable, "")
            if len(value) >= 8:
                cleaned = cleaned.replace(value, "***")
    return cleaned


def _normalise(name: str, raw: Any) -> ProbeResult:
    status = getattr(raw, "status", "error")
    if status not in ("ok", "skipped", "error"):
        status = "error"
    return ProbeResult(
        name=name,
        status=status,
        detail=scrub(str(getattr(raw, "detail", "") or "")),
        warnings=tuple(scrub(str(w)) for w in (getattr(raw, "warnings", ()) or ())),
    )


def run_probe(spec: KeySpec) -> ProbeResult:
    """Run one probe and return a result; never raises and never exposes a value.

    A missing variable gives ``error`` for a required service and ``skipped`` for an optional one,
    without calling the probe.
    """
    missing = missing_variables(spec)
    if missing:
        names = ", ".join(missing)
        if spec.required:
            return ProbeResult(spec.name, "error", f"falta {names} (obligatoria)")
        return ProbeResult(spec.name, "skipped", f"OMITIDA (opcional, falta {names})")
    if spec.probe is None:
        return ProbeResult(spec.name, "skipped", "sin sonda registrada")
    try:
        raw = spec.probe()
        if inspect.isawaitable(raw):
            raw = asyncio.run(_await(raw))
    except Exception as exc:  # noqa: BLE001 - a probe must not break check_keys
        return ProbeResult(
            spec.name, "error", scrub(f"la sonda falló: {type(exc).__name__}")
        )
    return _normalise(spec.name, raw)


async def _await(awaitable: Awaitable[Any]) -> Any:
    return await awaitable
