"""Per-user rate limits for the routes that spend provider credits or post publicly.

The rates sit on the classes, so they work without an entry in ``DEFAULT_THROTTLE_RATES``.
The daily credit caps (``DjangoCreditLedger.ensure_room``) are the hard limit on Xpoz spend.
These throttles keep a burst of requests from racing past that check.
"""

from rest_framework.throttling import UserRateThrottle


class HandleSearchThrottle(UserRateThrottle):
    """A search can end in a paid Xpoz lookup. Cached answers count too."""

    scope = "handle_search"
    rate = "30/min"


class PublishThrottle(UserRateThrottle):
    """Publishing posts to a real network, and to X (paid) when ``X_LIVE_ENABLED`` is on."""

    scope = "publish"
    rate = "10/min"
