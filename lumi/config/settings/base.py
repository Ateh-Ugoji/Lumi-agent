"""Settings shared by every environment.

All values come from environment variables. ``lumi/.env`` is loaded first and never overrides
variables that already exist in the process environment. No value is ever written here.
"""

from __future__ import annotations

from pathlib import Path

from apps.core import env

BASE_DIR = Path(__file__).resolve().parents[2]  # lumi/

env.load_env_file(Path(env.get("LUMI_ENV_FILE") or BASE_DIR / ".env"))

DEBUG = env.get_bool("DEBUG", False)

# Required outside tests; dev and prod settings call env.ensure_secret_key.
SECRET_KEY = env.get("SECRET_KEY")

ALLOWED_HOSTS = env.get_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.connections",
]

AUTH_USER_MODEL = "accounts.User"
AUTH_TOKEN_TTL_DAYS = env.get_int("AUTH_TOKEN_TTL_DAYS", 30)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# PostgreSQL only. DATABASE_URL is mandatory; there is no SQLite fallback.
DATABASES = {"default": env.database_config()}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "es"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Never "*". The default is the Vite dev server (port 3010 in lumi/frontend/vite.config.ts).
CORS_ALLOWED_ORIGINS = env.get_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:3010,http://127.0.0.1:3010"
)
CSRF_TRUSTED_ORIGINS = env.get_list("CSRF_TRUSTED_ORIGINS", "")

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Authentication and the uniform error handler arrive in T3.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Lumi API",
    "DESCRIPTION": "API del backend de Lumi. Contrato en lumi/docs/CONTRATOS.md.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Shared state (OAuth state, pending MCP writes) must never live in process memory in production.
_REDIS_URL = env.get("REDIS_URL")
if _REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _REDIS_URL,
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Names only; values are read when needed. Required-key policy lives in apps/core/keys.py.
TOKEN_ENCRYPTION_KEY = env.get("TOKEN_ENCRYPTION_KEY")
TOKEN_ENCRYPTION_KEY_PREVIOUS = env.get("TOKEN_ENCRYPTION_KEY_PREVIOUS")
PUBLIC_BASE_URL = env.get("PUBLIC_BASE_URL")
FRONTEND_URL = env.get("FRONTEND_URL")

# Fail at startup when a required key is missing (apps.core.startup.check). Off in tests.
KEYS_ENFORCE_REQUIRED = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env.get("LOG_LEVEL", "INFO")},
}
