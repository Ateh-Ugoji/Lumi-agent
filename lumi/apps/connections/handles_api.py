"""Service behind ``/api/v1/handles``: the composer's @-handle dropdown.

Layers and prices are documented in ``handles/service.py``. A live lookup costs Xpoz credits,
so it happens only when ``XPOZ_LIVE_ENABLED`` is true and a key is set. Without them the search
still answers from Postgres and says why in ``reason``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from asgiref.sync import async_to_sync
from django.db.models import Sum
from django.utils import timezone

from .accounts import api_error_from, get_config
from .clients.xpoz import USER_SEARCH, XpozClient, user_search_credits
from .errors import SocialDataError
from .handles.live import XpozHandleLive
from .handles.ranking import PLATFORMS, normalize_query, parse_platforms
from .handles.service import HandleSearch
from .handles.types import HandleRow, HandleSearchResult
from .models import XpozCreditLedger
from .stores import DjangoCreditLedger, DjangoHandleStore

SAVED_LIMIT = 500
PLATFORM_LABELS = {
    "x": "X",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "linkedin": "LinkedIn",
    "facebook": "Facebook",
}


def make_live(user_id: int) -> XpozHandleLive:
    """The paid lookup. Tests replace this to inject a mock transport."""
    return XpozHandleLive(
        XpozClient(
            get_config(),
            ledger=DjangoCreditLedger(user_id),
            run_id=f"handles-{uuid.uuid4().hex[:12]}",
        )
    )


def row_dict(row: HandleRow) -> dict[str, Any]:
    return {
        "handle": row.handle,
        "display_name": row.display_name,
        "avatar_url": row.avatar_url,
        "followers": row.followers,
        "source": row.source,
        "platform": row.platform,
    }


def search(user, q: str, context: str, platforms: str) -> dict[str, Any]:
    config = get_config()
    engine = HandleSearch(
        DjangoHandleStore(user.id),
        make_live(user.id),
        ttl_minutes=config.handle_cache_ttl_minutes,
    )
    try:
        result: HandleSearchResult = async_to_sync(engine.search)(
            q, platforms=platforms, context=context
        )
    except SocialDataError as exc:
        raise api_error_from(exc) from exc
    return {
        "query": result.query,
        "results": [row_dict(r) for r in result.results],
        "live": result.live,
        "refreshed": result.refreshed,
        "reason": result.reason,
        "context": result.context,
        "platforms": list(result.platforms),
        "platform_reasons": dict(result.platform_reasons),
    }


def saved(user, platforms: str) -> dict[str, Any]:
    rows = DjangoHandleStore(user.id).saved(parse_platforms(platforms), SAVED_LIMIT)
    return {"results": [row_dict(r) for r in rows], "count": len(rows)}


def select(user, data: dict[str, Any]) -> dict[str, Any] | None:
    """Remember a picked handle. ``None`` means the handle is not a valid name."""
    row = HandleRow(
        handle=normalize_query(data["handle"]),
        platform=data["platform"],
        display_name=data.get("display_name", ""),
        avatar_url=data.get("avatar_url", ""),
        followers=data.get("followers"),
        source="live",
    )
    name = DjangoHandleStore(user.id).select(row)
    if name is None:
        return None
    return {"remembered": True, "handle": name, "platform": row.platform}


def stats(user) -> dict[str, Any]:
    config = get_config()
    since = timezone.now() - timedelta(hours=24)
    spent = XpozCreditLedger.objects.filter(user_id=user.id, created_at__gte=since)
    store = DjangoHandleStore(user.id)
    return {
        "live_enabled": config.xpoz_live_enabled and bool(config.xpoz_api_keys),
        "live_budget": config.xpoz_run_credit_budget,
        "live_budget_by_platform": {
            p: config.xpoz_budget_for(p) for p in PLATFORMS if p in USER_SEARCH
        },
        "daily_cap_user": config.xpoz_daily_cap_user,
        "daily_cap_global": config.xpoz_daily_cap_global,
        "credits_spent_24h": spent.aggregate(total=Sum("credits"))["total"] or 0,
        "cache_ttl_minutes": config.handle_cache_ttl_minutes,
        "saved_handles": len(store.saved(list(PLATFORMS), SAVED_LIMIT)),
        **store.counts(),
        "available_platforms": [
            {
                "id": p,
                "label": PLATFORM_LABELS.get(p, p),
                "live": p in USER_SEARCH,
                "credits": user_search_credits(p) if p in USER_SEARCH else 0,
            }
            for p in PLATFORMS
        ],
    }
