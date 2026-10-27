"""Registry of external services and their keys.

Each app registers its services in ``AppConfig.ready()``:

    from apps.core import keys
    keys.register(keys.KeySpec(name="groq", variables=("GROQ_API_KEY",), required=True, probe=probe_groq))

``validate_required()`` lists every missing required variable at once. ``check_keys`` runs the
probes. Probes make a minimal real call and must never put a key value in their detail.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger("lumi.keys")

ProbeStatus = Literal["ok", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    detail: str = ""


Probe = Callable[[], ProbeResult]


@dataclass(frozen=True, slots=True)
class KeySpec:
    """One service. ``name`` is the stable id used by ``check_keys --only``.

    Plan names: nombre = name, obligatoria = required, sonda = probe.
    ``variables`` are all needed for the service to count as configured.
    """

    name: str
    variables: tuple[str, ...]
    required: bool = False
    probe: Probe | None = None
    description: str = ""
    # Variables that hold secrets; only these are scrubbed from probe output.
    secret_variables: tuple[str, ...] = field(default=())


_REGISTRY: dict[str, KeySpec] = {}


def register(spec: KeySpec) -> None:
    """Register a service. Registering the same name twice with the same spec is a no-op."""
    existing = _REGISTRY.get(spec.name)
    if existing is not None and existing != spec:
        raise ImproperlyConfigured(
            f"El servicio de keys '{spec.name}' ya está registrado con otra definición."
        )
    _REGISTRY[spec.name] = spec


def all_specs() -> list[KeySpec]:
    return list(_REGISTRY.values())


def get_spec(name: str) -> KeySpec | None:
    return _REGISTRY.get(name)


def missing_variables(spec: KeySpec) -> list[str]:
    return [var for var in spec.variables if not os.environ.get(var, "").strip()]


def is_configured(spec: KeySpec) -> bool:
    return not missing_variables(spec)


def missing_required() -> list[str]:
    names: list[str] = []
    for spec in _REGISTRY.values():
        if spec.required:
            names.extend(missing_variables(spec))
    return sorted(set(names))


def missing_optional() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for spec in _REGISTRY.values():
        if not spec.required and missing_variables(spec):
            result[spec.name] = missing_variables(spec)
    return result


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
    """Remove any configured secret value from ``text`` before it is shown or logged."""
    cleaned = text
    for spec in _REGISTRY.values():
        for variable in spec.secret_variables or spec.variables:
            value = os.environ.get(variable, "")
            if len(value) >= 6:
                cleaned = cleaned.replace(value, "***")
    return cleaned
