from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MCPAuthAccount(SQLModel, table=True):
    """OAuth tokens for one MCP connector auth account (e.g. `account="google"`).

    One row per consented auth account, not per connector: Google's Drive and
    Docs MCP servers are both satisfied by a single token whose scope set is
    the union of what every `auth="google_oauth"` connector requests. Written
    by the OAuth callback (`/mcp/google/callback`), refreshed transparently by
    `app.services.mcp` when the access token nears expiry.

    Secrets rule: access/refresh tokens live only here (DB), never in code,
    docs, or logs. The OAuth client id/secret live only in env vars.
    """

    __tablename__ = "mcp_auth_accounts"

    id: int | None = Field(default=None, primary_key=True)
    account: str = Field(unique=True, index=True)  # "google"
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    scopes: str | None = None  # space-joined granted scopes
    expires_at: datetime | None = None  # UTC; None = no expiry reported
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
