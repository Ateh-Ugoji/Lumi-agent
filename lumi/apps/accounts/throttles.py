"""Login and register attempts: 10 per minute per IP and 10 per minute per email."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class AuthIpThrottle(SimpleRateThrottle):
    scope = "auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": "auth_ip",
            "ident": self.get_ident(request),
        }


class AuthEmailThrottle(SimpleRateThrottle):
    scope = "auth"

    def get_cache_key(self, request, view):
        email = request.data.get("email") if isinstance(request.data, dict) else None
        if not isinstance(email, str) or not email.strip():
            return None
        return self.cache_format % {
            "scope": "auth_email",
            "ident": email.strip().lower(),
        }
