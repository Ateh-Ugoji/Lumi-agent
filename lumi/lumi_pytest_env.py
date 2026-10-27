"""Pytest plugin (loaded with ``-p`` from pyproject) that picks Django test settings.

Until the legacy FastAPI tests in lumi/tests are retired (T12) they run with a SQLite
DATABASE_URL in some environments, and Django rejects SQLite. So Django settings are
selected only when DATABASE_URL is a PostgreSQL URL. Delete this file in T12 and set
DJANGO_SETTINGS_MODULE in pyproject instead.
"""

import os

url = os.environ.get("DATABASE_URL", "").strip().lower()
if url.startswith(("postgres://", "postgresql://")):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
