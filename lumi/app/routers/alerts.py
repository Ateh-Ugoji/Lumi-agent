from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select

from app.database import session_scope
from app.models.post import MetricSnapshot, Post
from app.services.metrics import current_and_baseline_velocity

router = APIRouter(prefix="/profiles", tags=["alerts"])


class AlertVelocity(BaseModel):
    likes_per_hour: float
    baseline_likes_per_hour: float


class Alert(BaseModel):
    post_id: int
    caption: str
    platform_post_id: str
    alerted_at: datetime
    velocity: AlertVelocity


class AlertsResponse(BaseModel):
    alerts: list[Alert]


@router.get("/{profile_id}/alerts/unread", response_model=AlertsResponse)
async def get_unread_alerts(profile_id: int) -> AlertsResponse:
    async with session_scope() as session:
        posts = (
            await session.exec(
                select(Post).where(
                    Post.profile_id == profile_id,
                    Post.alerted_at.is_not(None),
                    Post.alert_dismissed.is_(False),
                )
            )
        ).all()

        alerts = []
        for post in posts:
            snapshots = (
                await session.exec(select(MetricSnapshot).where(MetricSnapshot.post_id == post.id))
            ).all()
            current, baseline = current_and_baseline_velocity(list(snapshots))

            alerts.append(
                Alert(
                    post_id=post.id,
                    caption=post.caption,
                    platform_post_id=post.platform_post_id,
                    alerted_at=post.alerted_at,
                    velocity=AlertVelocity(likes_per_hour=current, baseline_likes_per_hour=baseline),
                )
            )

    return AlertsResponse(alerts=alerts)
