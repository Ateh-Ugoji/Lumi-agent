"""Ownership checks. A profile that is not the caller's looks like one that does not exist (404)."""

from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission


def get_owned_profile(user, profile_id):
    """Return the caller's ``SocialProfile`` or raise ``NotFound`` (also for a malformed id)."""
    from apps.profiles.models import SocialProfile  # lazy: profiles imports core

    try:
        pk = int(profile_id)
    except (TypeError, ValueError):
        raise NotFound from None
    profile = (
        SocialProfile.objects.select_related("handle").filter(pk=pk, user=user).first()
    )
    if profile is None:
        raise NotFound
    return profile


class IsProfileOwner(BasePermission):
    """Passes only when the ``profile_id`` of the request belongs to the caller.

    The id comes from the URL kwargs, then the query string, then the JSON body. A route with no
    ``profile_id`` is not restricted by this class. The owned profile is cached on
    ``request.profile`` so the view does not query it again.
    """

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        raw = view.kwargs.get("profile_id")
        if raw is None:
            raw = request.query_params.get("profile_id")
        if raw is None and isinstance(request.data, dict):
            raw = request.data.get("profile_id")
        if raw is None:
            return True
        request.profile = get_owned_profile(request.user, raw)
        return True


class IsStaffOrDebug(BasePermission):
    """OpenAPI schema and Swagger UI: open with ``DEBUG=True``, staff only otherwise.

    ``settings.DEBUG`` is read per request. Staff sign in at ``/admin/`` and the session cookie
    then opens ``/api/docs/``; a staff API token works too.
    """

    def has_permission(self, request, view) -> bool:
        from django.conf import settings

        user = request.user
        return bool(
            settings.DEBUG or (user and user.is_authenticated and user.is_staff)
        )
