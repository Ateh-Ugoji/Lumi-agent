"""Typed environment access and DATABASE_URL parsing.

Every setting that comes from the environment goes through this module so the
error messages are uniform and never print a value. Real environment variables
win over the ``lumi/.env`` file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

DATABASE_URL_HINT = (
    "Define DATABASE_URL en lumi/.env con el formato postgresql://usuario:clave@host:5432/lumi. "
    "En local: `docker compose up -d db` o `uv run python scripts/dev_postgres.py`, que imprime la URL. "
    "Lumi solo usa PostgreSQL; no hay SQLite."
)

# Commands that must work with an empty environment so they can report what is missing.
LENIENT_COMMANDS = frozenset({"check_keys", "help", "version", "--help", "--version"})

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def is_lenient_invocation(argv: list[str] | None = None) -> bool:
    argv = sys.argv if argv is None else argv
    return len(argv) > 1 and argv[1] in LENIENT_COMMANDS


def _parse_env_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export ") :].lstrip()
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if not key.replace("_", "").isalnum():
        return None
    if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) >= 2:
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value


def load_env_file(path: Path) -> list[str]:
    """Load KEY=VALUE pairs from ``path`` without overriding real environment variables.

    Returns the names that were loaded (never the values).
    """
    loaded: list[str] = []
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw)
        if parsed is None:
            continue
        key, value = parsed
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} debe ser true o false.")


def get_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} debe ser un número entero.") from exc


def get_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        raw = default
    return [item.strip() for item in raw.split(",") if item.strip()]


def require(name: str, hint: str = "") -> str:
    value = get(name)
    if not value:
        message = f"Falta la variable de entorno obligatoria {name}."
        if hint:
            message = f"{message} {hint}"
        raise ImproperlyConfigured(message)
    return value


def parse_database_url(url: str) -> dict[str, Any]:
    """Turn a PostgreSQL URL into a Django ``DATABASES`` entry.

    Accepts ``postgresql://`` and ``postgres://`` (optionally ``+psycopg``), and the
    pgserver socket form ``postgresql://postgres:@/postgres?host=/path/to/socket``.
    Anything else fails with a message that names ``DATABASE_URL`` and never echoes
    the URL, because it can carry a password.
    """
    raw = url.strip()
    if not raw:
        raise ImproperlyConfigured(f"DATABASE_URL está vacía. {DATABASE_URL_HINT}")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme.startswith("sqlite"):
        raise ImproperlyConfigured(
            "DATABASE_URL apunta a SQLite y Lumi no lo admite. " + DATABASE_URL_HINT
        )
    if scheme in {"postgresql+asyncpg", "postgres+asyncpg"}:
        raise ImproperlyConfigured(
            "DATABASE_URL usa el esquema +asyncpg, que era del backend FastAPI. "
            "Usa el formato Django: postgresql://usuario:clave@host:5432/lumi."
        )
    if scheme not in {
        "postgresql",
        "postgres",
        "postgresql+psycopg",
        "postgres+psycopg",
    }:
        raise ImproperlyConfigured(
            "DATABASE_URL tiene un esquema no admitido. " + DATABASE_URL_HINT
        )

    query = dict(parse_qsl(parts.query, keep_blank_values=False))
    host = parts.hostname or ""
    socket_host = query.pop("host", "")
    if socket_host:
        host = unquote(socket_host)
    name = unquote(parts.path.lstrip("/"))
    if not name:
        raise ImproperlyConfigured(
            "DATABASE_URL no incluye el nombre de la base (…/lumi al final). "
            + DATABASE_URL_HINT
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise ImproperlyConfigured("DATABASE_URL tiene un puerto inválido.") from exc

    config: dict[str, Any] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": host,
        "PORT": str(port) if port else "",
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
    if query:
        config["OPTIONS"] = query
    return config


def database_config() -> dict[str, Any]:
    """Return the default database entry, failing clearly when DATABASE_URL is missing.

    Lenient commands (``check_keys``, ``help``, ``version``) get an inert placeholder so they can
    run with an empty environment and report the missing variable themselves.
    """
    url = get("DATABASE_URL")
    if not url:
        if is_lenient_invocation():
            return {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "lumi_unconfigured",
            }
        raise ImproperlyConfigured(
            f"Falta la variable de entorno obligatoria DATABASE_URL. {DATABASE_URL_HINT}"
        )
    return parse_database_url(url)


def ensure_secret_key(secret_key: str) -> str:
    """Fail clearly when SECRET_KEY is empty, except for lenient commands."""
    if secret_key:
        return secret_key
    if is_lenient_invocation():
        return "lenient-command-placeholder-not-a-secret"
    return require(
        "SECRET_KEY",
        'Genera una con: python -c "import secrets; print(secrets.token_urlsafe(50))"',
    )
