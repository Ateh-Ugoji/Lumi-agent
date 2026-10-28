"""The single routes table: which providers serve which platform, and in what order.

Every platform-to-provider decision lives in this one module (P1 of
``plan/TEMP-audit-publish-from-chat.md``, the decision it replaces was written in
three places: ``publish_api``, ``connect_links`` and ``ingest`` each kept their own
copy). New call sites read ``ROUTES`` (or the helpers) instead of defining their
own map.

Ordering is the routing preference: the native provider first, Post for Me
(``pfm``) as the fallback — the same preference ``connect_links`` always applied.
Capabilities mirror what the code does today: a native route declares exactly what
its adapter's ``capabilities()`` declares (checked against the adapters in
``tests/test_routes.py``), and ``pfm`` reads (``collect_own_posts``) but never
publishes (its posting call was never built).

This module is data only — no config, no environment, no network. Environment
gates (missing env vars, ``X_LIVE_ENABLED``) belong to the call site that asks
whether a provider is *ready*, not to the table that says who *serves* what.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Post for Me — the non-native router provider (an aggregator, not in
#: ``registry.OAUTH_PROVIDERS``).
PFM = "pfm"


@dataclass(frozen=True, slots=True)
class Route:
    """One provider's job for one platform.

    ``publish``/``read`` state what this route actually serves today: ``publish``
    is "holds the credentials for a publish of this platform", ``read`` is "serves
    own-posts/metric reads for this platform". Missing values stay honest —
    nothing here defaults to True.
    """

    provider: str
    publish: bool = False
    read: bool = False


#: platform -> providers in preference order (native first, ``pfm`` last).
ROUTES: dict[str, tuple[Route, ...]] = {
    "facebook": (Route("meta", publish=True, read=True), Route(PFM, read=True)),
    "instagram": (Route(PFM, read=True),),
    "linkedin": (Route("linkedin", publish=True), Route(PFM, read=True)),
    "tiktok": (Route(PFM, read=True),),
    # Native X reads are deliberately off (per-read pricing, providers/x.py); reads
    # stay on Xpoz / PFM, so the native route carries read=False.
    "x": (Route("x", publish=True), Route(PFM, read=True)),
}


def routes_for(platform: str) -> tuple[Route, ...]:
    """Preference-ordered routes for ``platform``; empty when nobody serves it."""
    return ROUTES.get(platform, ())


def publish_provider(platform: str) -> str | None:
    """The provider that publishes ``platform``, or ``None`` (unsupported).

    Instagram and TikTok have no publisher: ``pfm`` never built its posting call,
    so those platforms return ``None`` exactly as the old lookup did.
    """
    for route in routes_for(platform):
        if route.publish:
            return route.provider
    return None


def native_provider(platform: str) -> str | None:
    """The native (non-``pfm``) provider for ``platform``, or ``None``."""
    for route in routes_for(platform):
        if route.provider != PFM:
            return route.provider
    return None


#: Platforms Post for Me serves — derived from the table, so the two old
#: duplicate frozensets cannot drift apart again.
PFM_PLATFORMS: frozenset[str] = frozenset(
    platform
    for platform, routes in ROUTES.items()
    if any(route.provider == PFM for route in routes)
)
