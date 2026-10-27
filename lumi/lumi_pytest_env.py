"""Pytest plugin (loaded with ``-p`` from pyproject) that picks Django test settings.

Until the legacy FastAPI tests in lumi/tests are retired (T12) they run with a SQLite or empty
DATABASE_URL in some environments, and Django rejects SQLite. So Django settings are selected only
when DATABASE_URL is a PostgreSQL URL. When it is not, every test under ``apps/`` is skipped with a
reason that says why, instead of failing in confusing ways. Set LUMI_REQUIRE_DJANGO_TESTS=1 (CI does)
to turn that skip into a failure. Delete this file in T12 and set DJANGO_SETTINGS_MODULE in
pyproject instead.
"""

import os
from pathlib import Path

import pytest

url = os.environ.get("DATABASE_URL", "").strip().lower()
if url.startswith(("postgres://", "postgresql://")):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

_APPS_DIR = Path(__file__).resolve().parent / "apps"
_REASON = (
    "Los tests de apps/ necesitan DATABASE_URL con una URL de PostgreSQL "
    "(uv run python scripts/dev_postgres.py la imprime)."
)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DJANGO_SETTINGS_MODULE"):
        return
    strict = os.environ.get("LUMI_REQUIRE_DJANGO_TESTS") == "1"
    for item in items:
        if _APPS_DIR in Path(str(item.path)).parents:
            if strict:
                raise pytest.UsageError(_REASON)
            item.add_marker(pytest.mark.skip(reason=_REASON))
