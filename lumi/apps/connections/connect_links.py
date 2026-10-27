"""``ConnectionLinks`` port: mint the OAuth link the agent shows the user.

The tool only mints a URL. Minting still writes (the OAuth state row), so it runs through
``@aio``: when the tool call times out, the write rolls back and no state is left behind.
"""

from __future__ import annotations

from apps.core.errors import ApiError
from apps.intelligence.repos.aio import aio
from apps.profiles.models import SocialProfile
from lumi_ai.ports import (
    ConnectLink,
    LiveDisabled,
    Platform,
    ProviderUnavailable,
    UnsupportedPlatform,
)

from . import accounts
from .models import AccountStatus, ConnectedAccount

#: Native provider first, Post for Me as fallback. Instagram and TikTok only exist in Post for Me.
NATIVE_PROVIDER: dict[str, str] = {"facebook": "meta", "linkedin": "linkedin", "x": "x"}
PFM_PLATFORMS = frozenset({"x", "linkedin", "facebook", "instagram", "tiktok"})
_LIVE = (AccountStatus.ACTIVE, AccountStatus.LIMITED)


def choose_provider(platform: str) -> str | None:
    """The provider that can connect ``platform`` in this environment, or None."""
    config = accounts.get_config()
    native = NATIVE_PROVIDER.get(platform)
    native_ready = native and not accounts.missing_env(native, config)
    if native_ready and (native != "x" or config.x_live_enabled):
        return native
    if platform in PFM_PLATFORMS and not accounts.missing_env("pfm", config):
        return "pfm"
    return None


class DjangoConnectionLinks:
    async def start_connect(
        self, profile_id: int, platform: Platform, handle: str | None = None
    ) -> ConnectLink:
        return await _start(profile_id, platform, handle)


@aio
def _start(profile_id: int, platform: str, handle: str | None) -> ConnectLink:
    profile = SocialProfile.objects.select_related("user").filter(pk=profile_id).first()
    if profile is None:
        raise ProviderUnavailable("profile not found", provider="connections")
    live = (
        ConnectedAccount.objects.filter(
            user_id=profile.user_id, platform=platform, status__in=_LIVE
        )
        .defer(*accounts.TOKEN_COLUMNS)
        .order_by("id")
        .first()
    )
    if live is not None:
        return ConnectLink(
            already_connected=True,
            handle=live.handle or None,
            message=f"The {platform} account is already connected.",
        )
    provider = choose_provider(platform)
    if provider is None:
        raise UnsupportedPlatform(
            f"no provider is configured to connect {platform}", provider="connections"
        )
    try:
        url = accounts.start_connect(
            profile.user,
            provider,
            profile_id=profile_id,
            platform=platform if provider == "pfm" else None,
        )
    except ApiError as exc:
        if exc.api_code == "connections.live_disabled":
            raise LiveDisabled(str(exc.detail), provider=provider) from exc
        raise ProviderUnavailable(str(exc.detail), provider=provider) from exc
    return ConnectLink(already_connected=False, url=url, handle=handle)
