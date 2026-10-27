from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self) -> None:
        from apps.core import keys
        from apps.core.probes import (
            probe_database,
            probe_secret,
            probe_token_encryption,
        )

        keys.register(
            "database", probe_database, required=True, env_vars=("DATABASE_URL",)
        )
        keys.register("secret", probe_secret, required=True, env_vars=("SECRET_KEY",))
        keys.register(
            "token_encryption",
            probe_token_encryption,
            required=True,
            env_vars=("TOKEN_ENCRYPTION_KEY",),
        )
