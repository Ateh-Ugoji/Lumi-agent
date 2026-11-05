from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///lumi.db"
    pfm_jwt_token: str = ""

    groq_api_key: str
    openrouter_api_key: str
    openlux_api_key: str | None = None  # optional third provider; used first when set
    openlux_model: str = "qwen3.8-27b"
    typesafe_api_key: str
    neatlogs_api_key: str
    secret_key: str
    xpoz_api_key: str | None = None  # optional until the social-listening integration lands

    # Chroma (agentic storage: voice corpus, peer frameworks, agent memory)
    # Cloud when api_key is set (prod); PersistentClient at chroma_path otherwise (local dev)
    chroma_api_key: str | None = None
    chroma_tenant: str | None = None
    chroma_database: str | None = None
    chroma_path: str = ".chroma"

    # MCP connectors (Google Drive + Docs first; see app/services/mcp_connectors.py).
    # The client id/secret come from a Google Cloud OAuth client ("Web application"
    # + "Use this client for an AI-powered agent"); tokens live in the DB, never here.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Must match a redirect URI registered on the OAuth client.
    google_oauth_redirect_uri: str = "http://localhost:8000/mcp/google/callback"
    # Master switch + discovery/call budgets for every connector.
    mcp_enabled: bool = True
    mcp_tools_ttl_seconds: int = 300  # re-discover tools/list this often per connector
    mcp_refresh_timeout_seconds: int = 15  # per-turn budget for the TTL refresh
    mcp_call_timeout_seconds: int = 60  # single tools/call budget (loop caps the turn at 120s)

    # Turn classifier (L13 item 1 / PROMPT 5 item 1): rules run first at zero
    # latency; the Jev second stage only fires when NO rule matched, and only
    # when this kill-switch is on (spec-literal default: OFF).
    turn_class_jev_enabled: bool = False
    turn_class_jev_timeout_ms: int = 800  # hard cap on the stage-2 call
    # L13 item 8 banding: >= high -> act on any class; low..high -> act only
    # for free-tier classes (never start a credits/write path); < low -> "other".
    turn_class_jev_high: float = 0.85
    turn_class_jev_low: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()
