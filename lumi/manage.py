#!/usr/bin/env python
"""Django command-line entry point for Lumi."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. Corre `uv sync` dentro de lumi/ y vuelve a intentarlo."
        ) from exc
    from django.core.exceptions import ImproperlyConfigured

    try:
        execute_from_command_line(sys.argv)
    except ImproperlyConfigured as exc:
        sys.stderr.write(f"\nError de configuración: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
