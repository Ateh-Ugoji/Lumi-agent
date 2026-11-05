"""``OwnPostSync`` port: pull the profile's own posts from its connected Post for Me account.

``sync_own_posts`` reads the feed (``own_posts.collect_own_posts``), stores it through
``apps.profiles.services.upsert_posts`` and closes the pass (``passes.finalize_pass``), which marks
the posts the account stopped returning. The ingest rules (a missing metric stays NULL, kind and
thread fields) belong to ``apps.profiles.services`` and ``ingest.py``; nothing here fabricates a
value.

Each platform is read by the first route in ``providers.routes.ROUTES`` that can serve this
profile right now: a Facebook profile with a connected Page through Meta (posts, then the metrics
of the newest ones), a LinkedIn profile whose account holds ``r_member_social`` through LinkedIn
(posts only, it reports no metrics), an X profile through Xpoz when it is live (public read, the
metrics ride in the feed), and anything else through Post for Me as before. A native route that
cannot serve the profile (no connected account, a ``limited`` LinkedIn account, Xpoz off) falls
through to the next one, so the answer never depends on a route that cannot work.

Writes go through ``@aio``: when the ``backfill_posts`` tool times out, nothing it was still
writing commits afterwards. The feed read is an external call and stays outside the guard.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.core.fields import TokenDecryptError
from apps.intelligence.repos.aio import aio
from apps.profiles import services
from apps.profiles.models import SocialProfile
from lumi_ai.ports import (
    Platform,
    PostIn,
    ProviderUnavailable,
    UnsupportedPlatform,
)

from . import accounts
from .clients.xpoz import XpozClient
from .models import AccountStatus, ConnectedAccount, IngestSource, Provider
from .own_posts import collect_native_posts, collect_own_posts, collect_xpoz_posts
from .passes import finalize_pass, pass_reached_window
from .providers.base import AccountInfo, TokenSet
from .providers.routes import PFM, routes_for
from .socialdata import XpozSocialData
from .stores import DjangoCreditLedger, DjangoPassStore

#: Newest posts read per sync, and pages of 50 at most.
OWN_POST_LIMIT = 100
OWN_POST_MAX_PAGES = 10
#: Metrics are one Graph request per post, so only the newest posts get them on each sync.
META_METRICS_PER_SYNC = 20
_LIVE = (AccountStatus.ACTIVE, AccountStatus.LIMITED)


@dataclass(frozen=True, slots=True)
class _Target:
    handle_id: int
    platform: str
    handle: str
    account_id: str
    provider: str = Provider.PFM
    tokens: TokenSet | None = None
    info: AccountInfo | None = None
    user_id: int | None = None


#: The ``provider`` of a target read through Xpoz (not a ``ConnectedAccount`` provider).
XPOZ = "xpoz"
_SOURCE = {
    Provider.META: IngestSource.META,
    Provider.LINKEDIN: IngestSource.LINKEDIN,
    XPOZ: IngestSource.XPOZ,
    Provider.PFM: IngestSource.PFM,
}


class DjangoOwnPostSync:
    def __init__(self, passes: DjangoPassStore | None = None) -> None:
        self._passes = passes or DjangoPassStore()

    async def sync_own_posts(
        self, profile_id: int, platform: Platform | None = None
    ) -> dict[str, Any]:
        target = await sync_to_async(_target, thread_sensitive=True)(
            profile_id, platform
        )
        native = target.provider in (Provider.META, Provider.LINKEDIN)
        if native:
            started = timezone.now()
            result = await collect_native_posts(
                accounts.make_provider(target.provider),
                target.tokens,
                target.info,
                handle=target.handle,
                limit=OWN_POST_LIMIT,
                metrics_limit=META_METRICS_PER_SYNC,
            )
        elif target.provider == XPOZ:
            started = timezone.now()
            result = await collect_xpoz_posts(
                _xpoz_data(target.user_id), target.handle, limit=OWN_POST_LIMIT
            )
        else:
            config = accounts.get_config()
            if accounts.missing_env("pfm", config):
                raise ProviderUnavailable(
                    "Post for Me is not configured", provider=Provider.PFM
                )
            started = timezone.now()
            result = await collect_own_posts(
                accounts.make_pfm(),
                target.account_id,
                handle=target.handle,
                limit=OWN_POST_LIMIT,
                max_pages=OWN_POST_MAX_PAGES,
            )
        stored = await aio(_store)(target.handle_id, list(result.posts))
        dates = [p.published_at for p in result.posts]
        window = (min(dates), max(dates)) if dates else None
        # An empty read proves nothing (an outage looks the same), so it never counts as a pass.
        complete = bool(dates) and (
            result.stopped == "end" or pass_reached_window(min(dates), now=started)
        )
        outcome = await finalize_pass(
            self._passes,
            target.handle_id,
            fetched_ids={p.external_id for p in result.posts},
            source=_SOURCE[target.provider],
            pass_started=started,
            pass_complete=complete,
            fetched_window=window,
        )
        summary: dict[str, Any] = {
            "platform": target.platform,
            "handle": target.handle,
            "stored": stored,
            "skipped": result.skipped,
            "pages": result.pages,
            "complete": outcome.complete,
            "flagged_deleted": outcome.flagged_deleted,
        }
        if target.provider != Provider.PFM:
            summary["source"] = target.provider
        if native:
            summary["metrics_read"] = result.metrics_read
            summary["metrics_failed"] = result.metrics_failed
        return summary


def _target(profile_id: int, platform: str | None) -> _Target:
    row = (
        SocialProfile.objects.filter(pk=profile_id)
        .values_list("handle_id", "handle__platform", "handle__handle_normalized")
        .first()
    )
    if row is None:
        raise ProviderUnavailable("profile not found", provider="connections")
    handle_id, own_platform, handle = row
    if platform is not None and platform != own_platform:
        raise UnsupportedPlatform(
            f"this profile is on {own_platform}, not {platform}", provider="connections"
        )
    # ``read`` in the table is the adapter's static capability; LinkedIn (per-account scope) and X
    # (Xpoz) are decided in ``_native_target``, so every native route is asked, in order.
    for route in routes_for(own_platform):
        if route.provider == PFM:
            continue
        native = _native_target(
            profile_id, handle_id, own_platform, handle, route.provider
        )
        if native is not None:
            return native

    account = (
        ConnectedAccount.objects.filter(
            social_profile_id=profile_id, provider=Provider.PFM, status__in=_LIVE
        )
        .only("external_account_id")
        .order_by("id")
        .first()
    )
    if account is None:
        raise ProviderUnavailable(
            f"no connected {own_platform} account: connect one first",
            provider="connections",
        )
    return _Target(handle_id, own_platform, handle, account.external_account_id)


def _native_target(
    profile_id: int, handle_id: int, platform: str, handle: str, provider: str
) -> _Target | None:
    """The native route that can read this profile now, or None to try the next route."""
    if provider == Provider.X:
        return _xpoz_target(profile_id, handle_id, platform, handle)
    if provider not in (Provider.META, Provider.LINKEDIN):
        return None
    # A LINKEDIN account without r_member_social is ``limited``: it publishes but cannot read.
    statuses = (AccountStatus.ACTIVE,) if provider == Provider.LINKEDIN else _LIVE
    try:
        row = (
            ConnectedAccount.objects.filter(
                social_profile_id=profile_id, provider=provider, status__in=statuses
            )
            .order_by("id")
            .first()
        )
        if row is None:
            return None
        tokens = accounts.token_set(row)
    except TokenDecryptError:
        raise ProviderUnavailable(
            f"the stored {provider} connection cannot be read: connect the account again",
            provider="connections",
        ) from None
    info = AccountInfo(
        external_id=row.external_account_id,
        display_name=row.display_name,
        handle=row.handle or None,
        status=row.status,
    )
    return _Target(
        handle_id, platform, handle, row.external_account_id, provider, tokens, info
    )


def _xpoz_data(user_id: int | None) -> XpozSocialData:
    """The paid Xpoz reader. Tests replace this to inject a mock transport."""
    return XpozSocialData(
        XpozClient(
            accounts.get_config(),
            ledger=DjangoCreditLedger(user_id),
            run_id=f"own-posts-{uuid.uuid4().hex[:12]}",
        )
    )


def _xpoz_target(
    profile_id: int, handle_id: int, platform: str, handle: str
) -> _Target | None:
    """X is read by handle through Xpoz (native X reads are priced per resource, ``x.py``)."""
    config = accounts.get_config()
    if not (config.xpoz_live_enabled and config.xpoz_api_keys):
        return None
    user_id = SocialProfile.objects.values_list("user_id", flat=True).get(pk=profile_id)
    return _Target(handle_id, platform, handle, "", XPOZ, user_id=user_id)


def _store(handle_id: int, posts: list[PostIn]) -> int:
    """Save the posts and renumber each thread they belong to. Returns how many rows changed."""
    done = services.upsert_posts(handle_id, posts)
    for conversation_id in sorted(
        {p.conversation_id for p in posts if p.conversation_id}
    ):
        services.rethread_conversation(handle_id, conversation_id)
    return done.inserted + done.updated


__all__ = [
    "META_METRICS_PER_SYNC",
    "OWN_POST_LIMIT",
    "OWN_POST_MAX_PAGES",
    "DjangoOwnPostSync",
]
