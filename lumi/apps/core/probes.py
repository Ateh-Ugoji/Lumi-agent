"""Probes owned by apps.core: database, SECRET_KEY and TOKEN_ENCRYPTION_KEY."""

from __future__ import annotations

import os

from apps.core.keys import ProbeResult


def probe_database() -> ProbeResult:
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - report the class, never the connection string
        return ProbeResult(
            "failed", f"no se pudo consultar la base: {type(exc).__name__}"
        )
    return ProbeResult("ok", "SELECT 1 correcto")


def probe_secret() -> ProbeResult:
    value = os.environ.get("SECRET_KEY", "")
    if len(value) < 32:
        return ProbeResult("failed", "SECRET_KEY debe tener al menos 32 caracteres")
    return ProbeResult("ok", "longitud suficiente")


def probe_token_encryption() -> ProbeResult:
    from cryptography.fernet import Fernet

    value = os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    try:
        fernet = Fernet(value.encode())
        if fernet.decrypt(fernet.encrypt(b"lumi-probe")) != b"lumi-probe":
            return ProbeResult("failed", "el cifrado no devolvió el valor original")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(
            "failed",
            f"TOKEN_ENCRYPTION_KEY no es una clave Fernet válida ({type(exc).__name__})",
        )
    return ProbeResult("ok", "cifrado y descifrado correctos")
