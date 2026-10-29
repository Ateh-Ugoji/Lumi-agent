"""Run the minimal real call of every registered service and report.

    python manage.py check_keys [--only database,groq] [--json]

Exit codes: 0 when every required service is ok and no configured service failed,
1 when a required variable is missing or a configured probe failed, 2 for an unknown id.
Output never contains a key value.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.core import keys

LABELS = {"ok": "OK", "skipped": "OMITIDA", "error": "FALLA"}


class Command(BaseCommand):
    help = "Hace una llamada mínima real a cada servicio configurado y muestra el resultado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            default="",
            help="ids separados por coma, por ejemplo database,groq",
        )
        parser.add_argument("--json", action="store_true", help="salida en JSON")

    def handle(self, *args, **options):
        specs = keys.all_specs()
        wanted = [item.strip() for item in options["only"].split(",") if item.strip()]
        if wanted:
            known = {spec.name for spec in specs}
            unknown = [item for item in wanted if item not in known]
            if unknown:
                raise CommandError(
                    f"Ids desconocidos: {', '.join(unknown)}. Disponibles: {', '.join(sorted(known))}.",
                    returncode=2,
                )
            specs = [spec for spec in specs if spec.name in wanted]

        results = [(spec, keys.run_probe(spec)) for spec in specs]
        failed = any(result.status == "error" for _, result in results)

        if options["json"]:
            payload = [
                {
                    "name": result.name,
                    "required": spec.required,
                    "status": result.status,
                    "detail": result.detail,
                    "warnings": list(result.warnings),
                    "env_vars": list(spec.env_vars),
                }
                for spec, result in results
            ]
            self.stdout.write(
                json.dumps({"ok": not failed, "services": payload}, ensure_ascii=False)
            )
        else:
            for spec, result in results:
                tag = "obligatoria" if spec.required else "opcional"
                self.stdout.write(
                    f"{LABELS[result.status]:8} {result.name:18} ({tag}) {result.detail}"
                )
                for warning in result.warnings:
                    self.stdout.write(f"{'':8} {'':18} aviso: {warning}")
            if failed:
                self.stdout.write(
                    "Hay servicios con error. Revisa lumi/docs/API_KEYS.md."
                )
        if failed:
            raise SystemExit(1)
