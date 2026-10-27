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
DEFAULT_XPOZ_RUN_CREDIT_BUDGET = 10
DEFAULT_HANDLE_CACHE_TTL_MINUTES = 60
DEFAULT_MCP_TOOLS_TTL_SECONDS = 300
DEFAULT_MCP_CALL_TIMEOUT_SECONDS = 60
DEFAULT_MCP_REFRESH_TIMEOUT_SECONDS = 8

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


def parse_non_negative_int(value: str | None, *, name: str, default: int) -> int:
    text = (value or "").strip()
    if not text:
        return default
    try:
        number = int(text)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number") from None
    if number < 0:
        raise ConfigError(f"{name} must not be negative")
    return number


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
    pfm_jwt_token: str = field(default="", repr=False)
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    google_redirect_uri: str = ""
    mcp_tools_ttl_seconds: int = DEFAULT_MCP_TOOLS_TTL_SECONDS
    mcp_call_timeout_seconds: int = DEFAULT_MCP_CALL_TIMEOUT_SECONDS
    mcp_refresh_timeout_seconds: int = DEFAULT_MCP_REFRESH_TIMEOUT_SECONDS
    xpoz_api_key: str = field(default="", repr=False)
    xpoz_api_key_2: str = field(default="", repr=False)
    xpoz_live_enabled: bool = False
    xpoz_run_credit_budget: int = DEFAULT_XPOZ_RUN_CREDIT_BUDGET
    handle_cache_ttl_minutes: int = DEFAULT_HANDLE_CACHE_TTL_MINUTES

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
            pfm_jwt_token=get("PFM_JWT_TOKEN"),
            google_client_id=get("GOOGLE_OAUTH_CLIENT_ID"),
            google_client_secret=get("GOOGLE_OAUTH_CLIENT_SECRET"),
            google_redirect_uri=get("GOOGLE_OAUTH_REDIRECT_URI"),
            mcp_tools_ttl_seconds=parse_non_negative_int(
                env.get("MCP_TOOLS_TTL_SECONDS"),
                name="MCP_TOOLS_TTL_SECONDS",
                default=DEFAULT_MCP_TOOLS_TTL_SECONDS,
            ),
            mcp_call_timeout_seconds=parse_non_negative_int(
                env.get("MCP_CALL_TIMEOUT_SECONDS"),
                name="MCP_CALL_TIMEOUT_SECONDS",
                default=DEFAULT_MCP_CALL_TIMEOUT_SECONDS,
            ),
            mcp_refresh_timeout_seconds=parse_non_negative_int(
                env.get("MCP_REFRESH_TIMEOUT_SECONDS"),
                name="MCP_REFRESH_TIMEOUT_SECONDS",
                default=DEFAULT_MCP_REFRESH_TIMEOUT_SECONDS,
            ),
            xpoz_api_key=get("XPOZ_API_KEY"),
            xpoz_api_key_2=get("XPOZ_API_KEY_2"),
            xpoz_live_enabled=parse_bool(
                env.get("XPOZ_LIVE_ENABLED"), name="XPOZ_LIVE_ENABLED"
            ),
            xpoz_run_credit_budget=parse_non_negative_int(
                env.get("XPOZ_RUN_CREDIT_BUDGET"),
                name="XPOZ_RUN_CREDIT_BUDGET",
                default=DEFAULT_XPOZ_RUN_CREDIT_BUDGET,
            ),
            handle_cache_ttl_minutes=parse_non_negative_int(
                env.get("HANDLE_CACHE_TTL_MINUTES"),
                name="HANDLE_CACHE_TTL_MINUTES",
                default=DEFAULT_HANDLE_CACHE_TTL_MINUTES,
            ),
        )

    @property
    def xpoz_api_keys(self) -> tuple[str, ...]:
        """Configured Xpoz keys in rotation order, blanks dropped."""
        return tuple(k for k in (self.xpoz_api_key, self.xpoz_api_key_2) if k)

    def redirect_uri(self, provider: str) -> str:
        if provider == "google" and self.google_redirect_uri:
            return self.google_redirect_uri
        return f"{self.public_base_url}/api/v1/connections/{provider}/callback"
