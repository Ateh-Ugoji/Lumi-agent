from apps.core import env

from .base import *

DEBUG = False
SECRET_KEY = env.ensure_secret_key(SECRET_KEY)

# Railway terminates TLS in front of the app.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.get_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.get_int("SECURE_HSTS_SECONDS", 0)
SECURE_CONTENT_TYPE_NOSNIFF = True
