"""Import the legacy SQLite ``lumi.db`` into PostgreSQL.

    python manage.py import_legacy --sqlite PATH [--user EMAIL] [--dry-run] [--memory-md PATH]
    python manage.py import_legacy --sqlite PATH --verify

The SQLite file is opened read-only. The output carries counts and ids, never values.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from apps.core.legacy_import import ImportConflict, run_import, verify_import


class Command(BaseCommand):
    help = "Importa el lumi.db del sistema anterior (solo lectura) a PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True, help="ruta del lumi.db legado")
        parser.add_argument(
            "--user",
            default=None,
            help="email del usuario dueño de los datos (por defecto importado@lumi.invalid)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="ejecuta todo y deshace la transacción al final",
        )
        parser.add_argument(
            "--memory-md", default=None, help="ruta del memory.md legado"
        )
        parser.add_argument(
            "--verify",
            action="store_true",
            help="no importa: compara las filas del origen con lo registrado",
        )

    def handle(self, *args, **options):
        path = options["sqlite"]
        try:
            if options["verify"]:
                return self._verify(path)
            report = run_import(
                path,
                user_email=options["user"],
                dry_run=options["dry_run"],
                memory_md=options["memory_md"],
            )
        except ImproperlyConfigured as exc:
            # Discarded rows keep an encrypted copy, so the import needs TOKEN_ENCRYPTION_KEY.
            raise CommandError(str(exc)) from exc
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc
        except ImportConflict as exc:
            raise CommandError(
                f"Importación cancelada, no se guardó nada: {exc}"
            ) from exc
        for line in report.lines():
            self.stdout.write(line)
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Simulacro: no se guardó nada."))
        else:
            self.stdout.write(self.style.SUCCESS("Importación terminada."))

    def _verify(self, path: str) -> None:
        rows = verify_import(path)
        for row in rows:
            self.stdout.write(
                f"{row.table}: origen {row.legacy}, registradas {row.accounted} "
                f"(importadas {row.imported}, fusionadas {row.merged}, omitidas {row.skipped}), "
                f"{row.status}"
            )
        bad = [r for r in rows if not r.ok]
        if bad:
            names = ", ".join(f"{r.table} ({r.status})" for r in bad)
            raise CommandError(f"La verificación falló en: {names}")
        self.stdout.write(
            self.style.SUCCESS("Verificación correcta: las 21 tablas cuadran.")
        )
