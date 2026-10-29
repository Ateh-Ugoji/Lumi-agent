"""Per-user limits for the routes that cost money (LLM calls)."""

from rest_framework.throttling import UserRateThrottle


class ChatUserThrottle(UserRateThrottle):
    """``DEFAULT_THROTTLE_RATES["chat"]`` per authenticated user, shared by every chat route."""

    scope = "chat"
