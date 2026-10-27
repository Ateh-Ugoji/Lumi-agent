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
            keys.KeySpec(
                name="database",
                variables=("DATABASE_URL",),
                required=True,
                probe=probe_database,
                secret_variables=("DATABASE_URL",),
            )
        )
        keys.register(
            keys.KeySpec(
                name="secret",
                variables=("SECRET_KEY",),
                required=True,
                probe=probe_secret,
            )
        )
        keys.register(
            keys.KeySpec(
                name="token_encryption",
                variables=("TOKEN_ENCRYPTION_KEY",),
                required=True,
                probe=probe_token_encryption,
            )
        )
