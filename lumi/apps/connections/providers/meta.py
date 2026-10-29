"""Meta adapter for Facebook Pages (Graph API).

Flow: the user authorizes, the server swaps the code for a short-lived user token, swaps that
for a long-lived one (``fb_exchange_token``), then lists the user's Pages. A Page token read
with a long-lived user token does not expire. Lumi stores the Page token per Page.

Meta has no refresh token. ``refresh`` repeats the long-lived exchange for user tokens.

Sources, checked 2026-10-27:
https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow
https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
https://developers.facebook.com/docs/pages-api/getting-started
The revoke call (DELETE /me/permissions) and the 63,206 character limit are not confirmed
in today's official pages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from lumi_ai.ports import PostIn, PostMetrics

from ..config import ConnectionsConfig
from ..errors import ProviderAuthError, ProviderUnavailable
from ..http import ProviderHttp
from .base import (
    AccountInfo,
    AuthorizationRequest,
    Capabilities,
    PublishDraft,
    PublishResult,
    RevokeOutcome,
    SocialProvider,
    TokenSet,
    json_object,
    seconds_to_expiry,
)

SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "read_insights",
)
GRAPH_HOST = "graph.facebook.com"
HOSTS = frozenset({GRAPH_HOST})
# v25.0 retired the *_impressions_* metrics in favour of these.
POST_METRICS = ("post_media_view", "post_total_media_view_unique")


class MetaProvider(SocialProvider):
    name = "meta"
    platform = "facebook"

    def __init__(
        self, http: ProviderHttp, config: ConnectionsConfig, **kwargs: Any
    ) -> None:
        super().__init__(http, **kwargs)
        self._config = config
        self._graph = f"https://{GRAPH_HOST}/{config.meta_graph_version}"

    def _require_credentials(self) -> tuple[str, str]:
        if not (self._config.meta_app_id and self._config.meta_app_secret):
            raise ProviderUnavailable(
                "META_APP_ID and META_APP_SECRET are not set", provider=self.name
            )
        return self._config.meta_app_id, self._config.meta_app_secret

    def capabilities(self) -> Capabilities:
        return Capabilities(
            can_publish=True,
            can_read_posts=True,
            can_read_metrics=True,
            uses_pkce=False,
            supports_refresh=False,
            max_text_length=self.text_limit,
            scopes=SCOPES,
        )

    def build_authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str | None = None
    ) -> AuthorizationRequest:
        if not self._config.meta_app_id:
            raise ProviderUnavailable("META_APP_ID is not set", provider=self.name)
        query = urlencode(
            {
                "client_id": self._config.meta_app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": ",".join(SCOPES),
                "response_type": "code",
            }
        )
        url = f"https://www.facebook.com/{self._config.meta_graph_version}/dialog/oauth?{query}"
        return AuthorizationRequest(url=url, state=state)

    async def check_app_credentials(self) -> None:
        """Free credential check: ask Meta for an app access token (``client_credentials``).

        Needs only the app id and secret, no user. Raises a typed error when they are wrong.
        Documented at https://developers.facebook.com/docs/facebook-login/access-tokens
        (checked 2026-10-27).
        """
        app_id, secret = self._require_credentials()
        body = await self._token_request(
            {
                "client_id": app_id,
                "client_secret": secret,
                "grant_type": "client_credentials",
            }
        )
        if not body.get("access_token"):
            raise ProviderUnavailable(
                "app token response without access_token", provider=self.name
            )

    async def _token_request(self, params: dict[str, str]) -> dict[str, Any]:
        # The app secret and the exchanged token travel in the form body: a query string ends up
        # in the httpx INFO log and in proxy logs.
        response = await self._http.request(
            "POST", f"{self._graph}/oauth/access_token", data=params, retries=0
        )
        return json_object(response, self.name)

    def _user_tokens(self, body: dict[str, Any]) -> TokenSet:
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderUnavailable(
                "token response without access_token", provider=self.name
            )
        return TokenSet(
            access_token=access,
            expires_at=seconds_to_expiry(body.get("expires_in"), now=self._clock()),
            scopes=SCOPES,
            token_type=str(body.get("token_type") or "bearer"),
        )

    async def _long_lived(self, short_token: str) -> TokenSet:
        app_id, secret = self._require_credentials()
        body = await self._token_request(
            {
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": secret,
                "fb_exchange_token": short_token,
            }
        )
        return self._user_tokens(body)

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> TokenSet:
        app_id, secret = self._require_credentials()
        body = await self._token_request(
            {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "client_secret": secret,
                "code": code,
            }
        )
        short = self._user_tokens(body)
        return await self._long_lived(short.access_token)

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        """Repeat the long-lived exchange. Page tokens do not expire and need no refresh."""
        return await self._long_lived(tokens.access_token)

    async def revoke(self, tokens: TokenSet) -> RevokeOutcome:
        response = await self._http.request(
            "DELETE",
            f"{self._graph}/me/permissions",
            headers=_bearer(tokens.access_token),
            retries=0,
        )
        body = json_object(response, self.name)
        return RevokeOutcome(remote_revoked=bool(body.get("success")))

    async def get_account(self, tokens: TokenSet) -> AccountInfo:
        response = await self._http.request(
            "GET",
            f"{self._graph}/me",
            params={"fields": "id,name"},
            headers=_bearer(tokens.access_token),
            retries=1,
        )
        body = json_object(response, self.name)
        if not body.get("id"):
            raise ProviderUnavailable("unexpected /me response", provider=self.name)
        return AccountInfo(
            external_id=str(body["id"]),
            display_name=str(body.get("name") or body["id"]),
        )

    async def list_accounts(self, tokens: TokenSet) -> list[AccountInfo]:
        """List the Pages the user manages. Each carries its own Page token."""
        response = await self._http.request(
            "GET",
            f"{self._graph}/me/accounts",
            params={"fields": "id,name,access_token,tasks"},
            headers=_bearer(tokens.access_token),
            retries=1,
        )
        pages = json_object(response, self.name).get("data")
        if not isinstance(pages, list):
            raise ProviderUnavailable(
                "unexpected /me/accounts response", provider=self.name
            )
        accounts: list[AccountInfo] = []
        for page in pages:
            if (
                not isinstance(page, dict)
                or not page.get("id")
                or not page.get("access_token")
            ):
                continue
            tasks = page.get("tasks") or []
            can_post = "CREATE_CONTENT" in tasks
            accounts.append(
                AccountInfo(
                    external_id=str(page["id"]),
                    display_name=str(page.get("name") or page["id"]),
                    status="active" if can_post else "limited",
                    access_token=str(page["access_token"]),
                    note=None
                    if can_post
                    else "The user lacks the CREATE_CONTENT task on this Page.",
                )
            )
        return accounts

    def _page_token(self, account: AccountInfo, tokens: TokenSet) -> str:
        token = account.access_token or tokens.access_token
        if not token:
            raise ProviderAuthError("no Page token", provider=self.name)
        return token

    async def fetch_posts(
        self, tokens: TokenSet, account: AccountInfo, *, limit: int = 20
    ) -> list[PostIn]:
        response = await self._http.request(
            "GET",
            f"{self._graph}/{account.external_id}/posts",
            params={
                "fields": "id,message,created_time,permalink_url",
                "limit": max(1, min(limit, 100)),
            },
            headers=_bearer(self._page_token(account, tokens)),
            retries=1,
        )
        rows = json_object(response, self.name).get("data")
        if not isinstance(rows, list):
            raise ProviderUnavailable("unexpected posts response", provider=self.name)
        posts: list[PostIn] = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or not row.get("id")
                or not row.get("created_time")
            ):
                continue
            posts.append(
                PostIn(
                    platform="facebook",
                    external_id=str(row["id"]),
                    text=str(row.get("message") or ""),
                    published_at=_parse_time(str(row["created_time"])),
                    author_handle=None,
                    kind="original",
                    url=row.get("permalink_url"),
                    source="meta",
                )
            )
        return posts

    async def fetch_metrics(
        self, tokens: TokenSet, account: AccountInfo, post_id: str
    ) -> PostMetrics:
        response = await self._http.request(
            "GET",
            f"{self._graph}/{post_id}/insights",
            params={
                "metric": ",".join(POST_METRICS),
            },
            headers=_bearer(self._page_token(account, tokens)),
            retries=1,
        )
        rows = json_object(response, self.name).get("data")
        values: dict[str, int] = {}
        for row in rows if isinstance(rows, list) else []:
            try:
                values[row["name"]] = int(row["values"][0]["value"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return PostMetrics(views=values.get("post_media_view"))

    async def publish(
        self,
        tokens: TokenSet,
        account: AccountInfo,
        draft: PublishDraft,
        *,
        dry_run: bool = False,
    ) -> PublishResult:
        self.validate_draft(draft)
        if account.status == "limited":
            raise ProviderAuthError(
                account.note or "This Page cannot publish with this connection.",
                provider=self.name,
            )
        if dry_run:
            return PublishResult(external_post_id=None, url=None, dry_run=True)
        data: dict[str, str] = {
            "message": draft.text,
            "access_token": self._page_token(account, tokens),
        }
        if draft.link:
            data["link"] = draft.link
        response = await self._http.request(
            "POST", f"{self._graph}/{account.external_id}/feed", data=data, retries=0
        )
        post_id = json_object(response, self.name).get("id")
        if not post_id:
            raise ProviderUnavailable("unexpected feed response", provider=self.name)
        return PublishResult(
            external_post_id=str(post_id),
            url=f"https://www.facebook.com/{post_id}",
            dry_run=False,
        )


def _bearer(token: str) -> dict[str, str]:
    """Graph accepts ``Authorization: Bearer``, so the token never enters a URL."""
    return {"Authorization": f"Bearer {token}"}


def _parse_time(value: str) -> datetime:
    # Graph returns "2026-10-01T12:00:00+0000". Python 3.11+ parses that offset.
    return datetime.fromisoformat(value)
