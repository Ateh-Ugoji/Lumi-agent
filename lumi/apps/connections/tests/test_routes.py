"""P1 — the routes table is the single owner of platform -> providers + capabilities.

The old decision lived in three duplicated maps (`PROVIDER_FOR_PLATFORM`,
`NATIVE_PROVIDER`, two `PFM_PLATFORMS` frozensets). These tests pin the four
behaviours the call sites rely on — publish lookup, native lookup, PFM membership
and provider preference order — and, most importantly, that the table's
capabilities never drift from what each adapter declares in `capabilities()`.
"""

from __future__ import annotations

from apps.connections.config import ConnectionsConfig
from apps.connections.providers.registry import OAUTH_PROVIDERS, build_provider
from apps.connections.providers.routes import (
    PFM,
    PFM_PLATFORMS,
    ROUTES,
    native_provider,
    publish_provider,
    routes_for,
)

CONFIG = ConnectionsConfig.from_env({})

#: Exactly the set both duplicate frozensets carried before P1.
HISTORICAL_PFM_PLATFORMS = frozenset(
    {"x", "linkedin", "facebook", "instagram", "tiktok"}
)


def test_publish_provider_matches_the_old_lookup() -> None:
    assert publish_provider("facebook") == "meta"
    assert publish_provider("linkedin") == "linkedin"
    assert publish_provider("x") == "x"
    # No publisher: pfm's posting call was never built, and the old map returned
    # None for these too.
    assert publish_provider("instagram") is None
    assert publish_provider("tiktok") is None
    assert publish_provider("threads") is None


def test_native_provider_matches_the_old_lookup() -> None:
    assert native_provider("facebook") == "meta"
    assert native_provider("linkedin") == "linkedin"
    assert native_provider("x") == "x"
    assert native_provider("instagram") is None
    assert native_provider("tiktok") is None
    assert native_provider("threads") is None


def test_pfm_platforms_replaces_both_duplicate_frozensets() -> None:
    assert PFM_PLATFORMS == HISTORICAL_PFM_PLATFORMS


def test_native_comes_first_and_pfm_is_always_the_fallback() -> None:
    for platform, platform_routes in ROUTES.items():
        providers = [route.provider for route in platform_routes]
        assert providers.count(PFM) <= 1, platform
        if PFM in providers:
            assert providers[-1] == PFM, platform
        native = native_provider(platform)
        assert providers[0] == (native if native else PFM), platform
        assert platform in PFM_PLATFORMS if PFM in providers else True


def test_pfm_never_publishes_and_every_platform_is_readable() -> None:
    for platform, platform_routes in ROUTES.items():
        assert any(route.read for route in platform_routes), platform
        for route in platform_routes:
            if route.provider == PFM:
                assert route.publish is False, platform


def test_native_routes_agree_with_the_adapter_capabilities() -> None:
    """The table must not drift from what each adapter declares itself able to do."""
    seen: set[str] = set()
    for provider_name in OAUTH_PROVIDERS:
        provider = build_provider(provider_name, CONFIG)
        caps = provider.capabilities()
        hosts = [
            platform
            for platform, platform_routes in ROUTES.items()
            if any(route.provider == provider_name for route in platform_routes)
        ]
        assert hosts, f"{provider_name} has no route"
        assert len(hosts) == 1, f"{provider_name} appears on {hosts}"
        route = next(
            route
            for route in routes_for(hosts[0])
            if route.provider == provider_name
        )
        assert route.publish is caps.can_publish, provider_name
        assert route.read is caps.can_read_posts, provider_name
        seen.add(provider_name)
    assert seen == set(OAUTH_PROVIDERS)


def test_unknown_platform_has_no_routes() -> None:
    assert routes_for("threads") == ()
    assert routes_for("") == ()
