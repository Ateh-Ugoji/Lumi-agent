"""``Authorization: Token <key>`` against ``auth_tokens`` (docs/CONTRATOS.md section 2)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from apps.accounts.models import AuthToken

KEYWORD = "Token"
TOUCH_EVERY = timedelta(hours=1)


class TokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != KEYWORD.lower().encode():
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Cabecera de autorización inválida.")
        try:
            key = parts[1].decode()
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Clave inválida.") from None
        token = AuthToken.lookup(key)
        if token is None:
            raise exceptions.AuthenticationFailed("Clave inválida o caducada.")
        now = timezone.now()
        if token.last_used_at is None or now - token.last_used_at > TOUCH_EVERY:
            AuthToken.objects.filter(pk=token.pk).update(last_used_at=now)
        return token.user, token

    def authenticate_header(self, request) -> str:
        return KEYWORD


class TokenAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.TokenAuthentication"
    name = "tokenAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Valor: `Token <clave>`. La entrega `/auth/login` o `/auth/register`.",
        }
