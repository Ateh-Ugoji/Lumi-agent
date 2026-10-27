"""Connection settings read from an environment mapping.

Takes a ``Mapping`` instead of reading ``os.environ`` so tests pass a plain dict and Django
settings can pass ``os.environ`` later. Secrets are excluded from ``repr``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .errors import ConfigError

DEFAULT_PUBLIC_BASE_URL = "http://localhost:8000"
DEFAULT_FRONTEND_URL = "http://localhost:3010"
DEFAULT_LINKEDIN_VERSION = "202609"
DEFAULT_META_GRAPH_VERSION = "v26.0"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}
_LINKEDIN_VERSION = re.compile(r"^20\d{2}(0[1-9]|1[0-2])$")
_GRAPH_VERSION = re.compile(r"^v\d{1,3}\.\d{1,2}$")


def parse_bool(value: str | None, *, name: str) -> bool:
    """Parse a switch. Unknown spellings fail loudly so a typo cannot enable a paid API."""
    text = (value or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false")


@dataclass(frozen=True, slots=True)
class ConnectionsConfig:
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL
    frontend_url: str = DEFAULT_FRONTEND_URL
    x_live_enabled: bool = False
    linkedin_api_version: str = DEFAULT_LINKEDIN_VERSION
    meta_graph_version: str = DEFAULT_META_GRAPH_VERSION
    meta_app_id: str = ""
    meta_app_secret: str = field(default="", repr=False)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = field(default="", repr=False)
    x_client_id: str = ""
    x_client_secret: str = field(default="", repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ConnectionsConfig:
        def get(name: str, default: str = "") -> str:
            return (env.get(name) or default).strip()

        li_version = get("LINKEDIN_API_VERSION", DEFAULT_LINKEDIN_VERSION)
        if not _LINKEDIN_VERSION.match(li_version):
            raise ConfigError("LINKEDIN_API_VERSION must look like YYYYMM")
        graph = get("META_GRAPH_VERSION", DEFAULT_META_GRAPH_VERSION)
        if not _GRAPH_VERSION.match(graph):
            raise ConfigError("META_GRAPH_VERSION must look like v26.0")
        return cls(
            public_base_url=get("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/"),
            frontend_url=get("FRONTEND_URL", DEFAULT_FRONTEND_URL).rstrip("/"),
            x_live_enabled=parse_bool(env.get("X_LIVE_ENABLED"), name="X_LIVE_ENABLED"),
            linkedin_api_version=li_version,
            meta_graph_version=graph,
            meta_app_id=get("META_APP_ID"),
            meta_app_secret=get("META_APP_SECRET"),
            linkedin_client_id=get("LINKEDIN_CLIENT_ID"),
            linkedin_client_secret=get("LINKEDIN_CLIENT_SECRET"),
            x_client_id=get("X_CLIENT_ID"),
            x_client_secret=get("X_CLIENT_SECRET"),
        )

    def redirect_uri(self, provider: str) -> str:
        return f"{self.public_base_url}/api/v1/connections/{provider}/callback"
