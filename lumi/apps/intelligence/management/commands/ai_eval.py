"""Evaluate the quality gate against the golden suite.

    python manage.py ai_eval --suite golden [--live] [--min-agreement 0.85] [--json]

Offline (default) the recorded rubric scores are replayed: it checks the gate and the
deterministic rules, needs no keys and costs nothing. ``--live`` asks the real judges (Jev,
then the small model of the provider chain) and spends their quota, so it is never the default.
The cases are synthetic; see ``lumi_ai/evaluation/golden``.

Exit code 0 when the agreement reaches ``--min-agreement``, non-zero otherwise.
"""

from __future__ import annotations

import asyncio
import json

from django.core.management.base import BaseCommand, CommandError

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.golden import RecordedScorer, load_cases, run_suite
from lumi_ai.evaluation.rubric import JevScorer, LLMScorer
from lumi_ai.judge.jev import JevJudge
from lumi_ai.providers.factory import build_chain


class Command(BaseCommand):
    help = "Mide cuánto coincide la puerta de calidad con las decisiones esperadas del conjunto dorado."

    def add_arguments(self, parser):
        parser.add_argument("--suite", default="golden", choices=["golden"])
        parser.add_argument(
            "--live",
            action="store_true",
            help="usa los jueces reales (gasta cuota de Jev y Groq); por defecto repite las notas grabadas",
        )
        parser.add_argument("--min-agreement", type=float, default=0.85)
        parser.add_argument("--json", action="store_true", help="salida en JSON")

    def handle(self, *args, **options):
        config = AIConfig.from_env()
        cases = load_cases()
        if options["live"]:
            jev = JevJudge(config)
            chain = build_chain(config)
            if not jev.available and not chain.providers:
                raise CommandError(
                    "--live necesita TYPESAFE_API_KEY o una clave de Groq/OpenRouter/OpenLux en lumi/.env."
                )
            scorers = [JevScorer(jev), LLMScorer(chain)]
        else:
            scorers = [RecordedScorer(cases)]
        report = asyncio.run(run_suite(cases, scorers, config))
        data = report.as_dict() | {"mode": "live" if options["live"] else "offline"}
        if options["json"]:
            self.stdout.write(json.dumps(data, indent=2))
        else:
            self.stdout.write(
                f"casos={data['cases']} (sintéticos) modo={data['mode']} "
                f"coincidencia={data['agreement']:.0%} regeneraciones={data['regeneration_rate']:.0%}"
            )
            self.stdout.write(f"decisiones={data['decisions']} jueces={data['judges']}")
            for miss in data["mismatches"]:
                self.stdout.write(
                    f"  DIFIERE {miss['id']}: esperado={miss['expected']} obtenido={miss['got']} juez={miss['judge']}"
                )
        if report.agreement < options["min_agreement"]:
            raise CommandError(
                f"coincidencia {report.agreement:.0%} por debajo del mínimo {options['min_agreement']:.0%}"
            )
