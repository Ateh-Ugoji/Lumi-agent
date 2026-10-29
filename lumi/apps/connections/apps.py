import logging

from django.apps import AppConfig

# These loggers write every request URL at INFO. Even with secrets moved out of query strings,
# a provider URL can carry an OAuth code, an id or a handle, so they stay at WARNING.
NOISY_HTTP_LOGGERS = (
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore.http11",
    "httpcore.connection",
)


def silence_http_loggers() -> None:
    for name in NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class ConnectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.connections"
    label = "connections"

    def ready(self) -> None:
        from .keys import register_all

        silence_http_loggers()
        register_all()
