"""Registers the AI providers' key probes with ``check_keys`` (``apps.core.keys``).

The probes themselves live in ``lumi_ai.keys`` (pure Python, no Django). This file only reads the
configuration once, through ``AIConfig.from_env()``, and registers one service per provider.
"""

from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.intelligence"
    label = "intelligence"

    def ready(self) -> None:
        from apps.intelligence.repos.voice import profiles_with_voice
        from apps.profiles import hooks

        hooks.set_voice_profile_reader(profiles_with_voice)
        from apps.core import keys
        from apps.intelligence import tasks  # noqa: F401 - registers the job handlers
        from lumi_ai.config import AIConfig
        from lumi_ai.keys import build_probes

        for probe in build_probes(AIConfig.from_env()):
            keys.register(
                probe.name,
                probe.run,
                required=probe.required,
                env_vars=probe.env_vars,
            )
