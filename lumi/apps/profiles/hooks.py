"""Readers that ``profiles`` needs from apps that depend on it, without importing them.

``profiles`` may not import ``intelligence`` or ``connections`` (they import ``profiles``).
Each reader is a plain callable the owning app can replace in its ``AppConfig.ready()``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from django.db import connection

from apps.core.choices import Platform

#: profile ids -> ids that have a current voice profile.
VoiceProfileReader = Callable[[Sequence[int]], set[int]]
#: profile id -> platforms with an active connected account.
ConnectedPlatformsReader = Callable[[Sequence[int]], Mapping[int, tuple[str, ...]]]


def _no_voice_profiles(profile_ids: Sequence[int]) -> set[int]:
    return set()


voice_profile_reader: VoiceProfileReader = _no_voice_profiles


def set_voice_profile_reader(reader: VoiceProfileReader) -> None:
    """INTELLIGENCE calls this from ``ready()`` with a query on ``voice_profiles``."""
    global voice_profile_reader
    voice_profile_reader = reader


# ``connected_accounts.provider`` -> the platforms it gives access to. ``pfm`` (Post for Me) is
# the publishing bridge of the profile's own network, so it maps to the profile's platform.
_PROVIDER_PLATFORMS = {
    "x": (Platform.X.value,),
    "linkedin": (Platform.LINKEDIN.value,),
    "meta": (Platform.FACEBOOK.value, Platform.INSTAGRAM.value),
}


def _connected_platforms_from_table(
    profile_ids: Sequence[int],
) -> Mapping[int, tuple[str, ...]]:
    """Default reader: queries ``connected_accounts`` by table name (owned by CONNECT)."""
    if not profile_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ca.social_profile_id, ca.provider, h.platform"
            " FROM connected_accounts ca"
            " JOIN social_profiles sp ON sp.id = ca.social_profile_id"
            " JOIN social_handles h ON h.id = sp.handle_id"
            " WHERE ca.status = 'active' AND ca.social_profile_id = ANY(%s)"
            " ORDER BY ca.social_profile_id, ca.provider",
            [list(profile_ids)],
        )
        rows = cursor.fetchall()
    found: dict[int, list[str]] = {}
    for profile_id, provider, own_platform in rows:
        platforms = (
            (own_platform,)
            if provider == "pfm"
            else _PROVIDER_PLATFORMS.get(provider, ())
        )
        bucket = found.setdefault(profile_id, [])
        bucket.extend(p for p in platforms if p not in bucket)
    return {pid: tuple(values) for pid, values in found.items()}


connected_platforms_reader: ConnectedPlatformsReader = _connected_platforms_from_table
