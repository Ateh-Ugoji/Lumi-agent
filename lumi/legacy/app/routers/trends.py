from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import select

from app.database import session_scope
from app.models.listening import ListeningMatch
from app.tools.listening import check_niche_trends

router = APIRouter(prefix="/trends", tags=["trends"])


class TrendMatchResponse(BaseModel):
    id: int
    profile_id: int
    platform: str
    platform_post_id: str
    author_handle: str
    author_avatar_url: str | None = None
    caption: str
    platform_url: str
    metrics: dict[str, Any] | None
    discovered_at: datetime


class TrendMatchesListResponse(BaseModel):
    matches: list[TrendMatchResponse]


class ScanTrendsRequest(BaseModel):
    profile_id: int = 1
    handles: list[str] = ["sama", "levelsio", "karpathy", "paulg", "swyx"]
    min_likes: int = 20


class ScanTrendsResponse(BaseModel):
    profile_id: int
    new_matches_found: int
    viral_posts: list[dict[str, Any]]


@router.get("/matches", response_model=TrendMatchesListResponse)
async def get_trend_matches(
    profile_id: int = Query(1),
    limit: int = Query(50),
) -> TrendMatchesListResponse:
    async with session_scope() as session:
        query = (
            select(ListeningMatch)
            .where(ListeningMatch.profile_id == profile_id)
            .order_by(ListeningMatch.discovered_at.desc())
            .limit(limit)
        )
        matches = (await session.exec(query)).all()

        return TrendMatchesListResponse(
            matches=[
                TrendMatchResponse(
                    id=m.id or 0,
                    profile_id=m.profile_id,
                    platform=m.platform,
                    platform_post_id=m.platform_post_id,
                    author_handle=m.author_handle,
                    author_avatar_url=m.author_avatar_url,
                    caption=m.caption,
                    platform_url=m.platform_url,
                    metrics=m.metrics,
                    discovered_at=m.discovered_at,
                )
                for m in matches
            ]
        )


@router.post("/scan", response_model=ScanTrendsResponse)
async def scan_trends(payload: ScanTrendsRequest) -> ScanTrendsResponse:
    result = await check_niche_trends(
        profile_id=payload.profile_id,
        handles=payload.handles,
        min_likes=payload.min_likes,
    )
    return ScanTrendsResponse(
        profile_id=result["profile_id"],
        new_matches_found=result["new_matches_found"],
        viral_posts=result["viral_posts"],
    )
