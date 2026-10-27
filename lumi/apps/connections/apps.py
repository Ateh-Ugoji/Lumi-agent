from django.apps import AppConfig


class ConnectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.connections"
    label = "connections"

    def ready(self) -> None:
        from .keys import register_all

        register_all()
