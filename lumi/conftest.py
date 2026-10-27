"""Root pytest hooks.

Tests marked ``live`` call a real service. They are collected everywhere but skipped unless
``LUMI_RUN_LIVE=1``, and each one still skips when the key it needs is missing. So a plain
``uv run pytest`` passes with no keys and no network.

The legacy FastAPI ``app.config.Settings`` has five fields with no default, so building it
without them raises. The tests in ``tests/`` never call a provider, so they get a placeholder for
each missing one. A value that is really set wins, and nothing is set when ``LUMI_RUN_LIVE=1``.
"""

import os
import sys
from pathlib import Path

import pytest

_LEGACY_TESTS = Path(__file__).parent / "tests"
# Every field of ``app.config.Settings`` that has no default.
_LEGACY_REQUIRED = (
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "TYPESAFE_API_KEY",
    "NEATLOGS_API_KEY",
    "SECRET_KEY",
)

_REASON = "test live: pon LUMI_RUN_LIVE=1 y las keys en lumi/.env para correrlo"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("LUMI_RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason=_REASON)
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True, scope="module")
def _legacy_settings_env(request):
    """Placeholders for the legacy ``Settings`` fields that no one set. Values are never printed.

    Module scope, so they exist before a module-scoped fixture starts ``alembic`` in a subprocess.
    """
    if (
        _LEGACY_TESTS not in request.path.parents
        or os.environ.get("LUMI_RUN_LIVE") == "1"
    ):
        yield
        return
    with pytest.MonkeyPatch.context() as patch:
        for name in _LEGACY_REQUIRED:
            if not os.environ.get(name):
                patch.setenv(name, "test-placeholder")
        _drop_settings_cache()
        yield
    _drop_settings_cache()


def _drop_settings_cache() -> None:
    config = sys.modules.get("app.config")
    if config is not None:
        config.get_settings.cache_clear()
