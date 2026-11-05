"""Provider URLs must not reach the logs: httpx logs each request at INFO by default."""

from __future__ import annotations

import logging

import httpx
import pytest

from apps.connections.apps import NOISY_HTTP_LOGGERS, silence_http_loggers


def test_http_client_loggers_are_quiet_after_the_app_is_ready() -> None:
    from django.apps import apps

    for name in NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    apps.get_app_config("connections").ready()
    for name in NOISY_HTTP_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


async def test_a_request_url_with_a_secret_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    silence_http_loggers()
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.INFO)  # what LOG_LEVEL=INFO does in settings
    try:
        with caplog.at_level(logging.INFO):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200))
            ) as client:
                await client.get("https://graph.example/me?access_token=SECRET-FAKE")
    finally:
        root.setLevel(previous)
    assert "SECRET-FAKE" not in caplog.text
