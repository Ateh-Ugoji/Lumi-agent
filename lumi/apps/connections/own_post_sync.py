"""``OwnPostSync`` port: pull the profile's own posts from its connected Post for Me account.

``sync_own_posts`` reads the feed (``own_posts.collect_own_posts``), stores it through
``apps.profiles.services.upsert_posts`` and closes the pass (``passes.finalize_pass``), which marks
the posts the account stopped returning. The ingest rules (a missing metric stays NULL, kind and
thread fields) belong to ``apps.profiles.services`` and ``ingest.py``; nothing here fabricates a
value.

Writes go through ``@aio``: when the ``backfill_posts`` tool times out, nothing it was still
writing commits afterwards. The feed read is an external call and stays outside the guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone

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
from .models import AccountStatus, ConnectedAccount, IngestSource, Provider
from .own_posts import collect_own_posts
from .passes import finalize_pass, pass_reached_window
from .stores import DjangoPassStore

#: Newest posts read per sync, and pages of 50 at most.
OWN_POST_LIMIT = 100
OWN_POST_MAX_PAGES = 10
_LIVE = (AccountStatus.ACTIVE, AccountStatus.LIMITED)


@dataclass(frozen=True, slots=True)
class _Target:
    handle_id: int
    platform: str
    handle: str
    account_id: str


class DjangoOwnPostSync:
    def __init__(self, passes: DjangoPassStore | None = None) -> None:
        self._passes = passes or DjangoPassStore()

    async def sync_own_posts(
        self, profile_id: int, platform: Platform | None = None
    ) -> dict[str, Any]:
        target = await sync_to_async(_target, thread_sensitive=True)(
            profile_id, platform
        )
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
            source=IngestSource.PFM,
            pass_started=started,
            pass_complete=complete,
            fetched_window=window,
        )
        return {
            "platform": target.platform,
            "handle": target.handle,
            "stored": stored,
            "skipped": result.skipped,
            "pages": result.pages,
            "complete": outcome.complete,
            "flagged_deleted": outcome.flagged_deleted,
        }


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


def _store(handle_id: int, posts: list[PostIn]) -> int:
    """Save the posts and renumber each thread they belong to. Returns how many rows changed."""
    done = services.upsert_posts(handle_id, posts)
    for conversation_id in sorted(
        {p.conversation_id for p in posts if p.conversation_id}
    ):
        services.rethread_conversation(handle_id, conversation_id)
    return done.inserted + done.updated


__all__ = ["OWN_POST_LIMIT", "OWN_POST_MAX_PAGES", "DjangoOwnPostSync"]
