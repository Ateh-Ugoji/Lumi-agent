"""Build providers by name. The only place that knows every adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import httpx

from ..config import ConnectionsConfig
from ..http import ProviderHttp
from .base import SocialProvider, utcnow
from .linkedin import HOSTS as LINKEDIN_HOSTS
from .linkedin import LinkedInProvider
from .meta import HOSTS as META_HOSTS
from .meta import MetaProvider
from .x import HOSTS as X_HOSTS
from .x import XProvider

OAUTH_PROVIDERS = ("meta", "linkedin", "x")


def build_provider(
    name: str,
    config: ConnectionsConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> SocialProvider:
    if name == "meta":
        return MetaProvider(
            ProviderHttp("meta", allowed_hosts=META_HOSTS, transport=transport),
            config,
            clock=clock,
        )
    if name == "linkedin":
        return LinkedInProvider(
            ProviderHttp("linkedin", allowed_hosts=LINKEDIN_HOSTS, transport=transport),
            config,
            clock=clock,
        )
    if name == "x":
        return XProvider(
            ProviderHttp("x", allowed_hosts=X_HOSTS, transport=transport),
            config,
            clock=clock,
        )
    raise KeyError(f"unknown provider: {name}")
