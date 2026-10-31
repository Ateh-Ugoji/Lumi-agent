"""Test settings: only DATABASE_URL is needed. No keys, no network."""

import os

# ``lumi/.env`` is loaded by ``base`` and never overrides a variable that already exists in
# the process, so setting these first keeps a development .env (Xpoz live, for example) from
# making the suite reach a provider. Without this, tests that assert "no account could be
# read" pass or fail depending on how the developer's .env is set.
for _switch in ("XPOZ_LIVE_ENABLED",):
    os.environ[_switch] = "false"

from .base import *

SECRET_KEY = "test-only-secret-not-for-use-outside-tests-0123456789"
KEYS_ENFORCE_REQUIRED = False
DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
