"""Test settings: only DATABASE_URL is needed. No keys, no network."""

from .base import *

SECRET_KEY = "test-only-secret-not-for-use-outside-tests-0123456789"
KEYS_ENFORCE_REQUIRED = False
DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
