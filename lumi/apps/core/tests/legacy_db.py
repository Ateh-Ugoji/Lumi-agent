"""Build a synthetic legacy ``lumi.db`` with the legacy SQLModel classes.

Rows go through the legacy models, so the file holds the same text the old code wrote
(naive datetimes as text, enums by name, JSON as text).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel


def dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def build_legacy_db(path: Path, *, populate=True) -> Path:
    import app.models as m  # the legacy models

    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    if populate:
        with Session(engine) as s:
            _fill(s, m)
            s.commit()
    engine.dispose()
    return path


def _fill(s: Session, m) -> None:
    # Profiles: 1 and 3 share a handle (3 must merge into 1); 4 has an unknown platform;
    # 5 has a handle X refuses.
    s.add_all(
        [
            m.Profile(
                id=1,
                name="Ateh",
                handle="@AtehOfficial",
                pfm_account_id="pfm-secret-111",
                created_at=dt(1),
                timezone="Africa/Lagos",
                timezone_source="user_confirmed",
            ),
            m.Profile(id=2, name="Demo", handle="demo_user", pfm_account_id="demo-1"),
            m.Profile(
                id=3, name="Dup", handle="atehofficial", pfm_account_id="pfm-secret-333"
            ),
            m.Profile(
                id=4, name="Odd", platform="myspace", handle="tom", pfm_account_id="p4"
            ),
            m.Profile(id=5, name="Bad", handle="not a handle!", pfm_account_id="p5"),
        ]
    )
    s.add_all(
        [
            m.ProfileSnapshot(
                id=1,
                profile_id=1,
                captured_at=dt(2),
                followers=100,
                following=10,
                source="pfm",
            ),
            m.ProfileSnapshot(
                id=2,
                profile_id=3,
                captured_at=dt(2),
                followers=150,
                following=12,
                source="xpoz",
            ),
            m.ProfileSnapshot(
                id=3, profile_id=1, captured_at=dt(3), followers=None, following=None
            ),
            m.ProfileSnapshot(id=4, profile_id=4, captured_at=dt(3), followers=1),
        ]
    )
    s.add_all(
        [
            m.ProfileBaseline(
                id=1,
                profile_id=1,
                n_posts=12,
                median_views=500.5,
                median_engagement=20.0,
                p75_views=900.0,
                baseline_reliable=True,
                computed_at=dt(5),
            ),
            m.ProfileBaseline(id=2, profile_id=2, n_posts=2),
        ]
    )
    s.add_all(
        [
            m.Post(
                id=10,
                profile_id=1,
                platform_post_id="p-1",
                caption="hello",
                published_at=dt(2),
                source="pfm",
                kind=None,
                conversation_id=None,
                alerted_at=dt(4),
                alert_dismissed=False,
            ),
            m.Post(
                id=11,
                profile_id=1,
                platform_post_id="p-2",
                caption="second",
                published_at=dt(3),
                kind="reply",
                kind_source="api",
                thread_position=1,
                is_thread_head=True,
                alerted_at=dt(4),
                alert_dismissed=True,
            ),
            m.Post(
                id=12,
                profile_id=3,
                platform_post_id="p-1",
                caption="hello again",
                published_at=dt(2),
            ),
            m.Post(
                id=13,
                profile_id=2,
                platform_post_id="p-1",
                caption="other account",
                published_at=dt(3),
                kind="weird",
            ),
            m.Post(
                id=14,
                profile_id=4,
                platform_post_id="p-9",
                caption="orphan",
                published_at=dt(3),
            ),
        ]
    )
    s.add_all(
        [
            m.MetricSnapshot(
                id=1,
                post_id=10,
                captured_at=dt(3),
                likes=5,
                comments=1,
                shares=0,
                views=100,
                age_hours=24.0,
                source="pfm",
            ),
            m.MetricSnapshot(
                id=2,
                post_id=10,
                captured_at=dt(4),
                likes=9,
                comments=None,
                shares=None,
                views=150,
            ),
            m.MetricSnapshot(id=3, post_id=12, captured_at=dt(3), likes=7, views=120),
            m.MetricSnapshot(id=4, post_id=11, captured_at=dt(4), likes=-3, views=10),
            m.MetricSnapshot(id=5, post_id=14, captured_at=dt(4), likes=1),
        ]
    )
    s.add_all(
        [
            m.UserActivity(
                id=1,
                profile_id=1,
                platform_post_id="r-1",
                kind="reply",
                caption="a reply",
                published_at=dt(2),
                likes=3,
                replies=1,
                views=40,
                source="xpoz",
                created_at=dt(6),
            ),
            m.UserActivity(
                id=2,
                profile_id=1,
                platform_post_id="rt-1",
                kind="retweet",
                caption="RT",
                published_at=dt(2),
                created_at=dt(6),
            ),
            m.UserActivity(
                id=3,
                profile_id=1,
                platform_post_id="p-1",
                kind="reply",
                caption="dup of a post",
                published_at=dt(2),
            ),
            m.UserActivity(
                id=4,
                profile_id=1,
                platform_post_id="x-1",
                kind="bookmark",
                caption="?",
                published_at=dt(2),
            ),
        ]
    )
    s.add_all(
        [
            m.ListeningMatch(
                id=1,
                profile_id=1,
                platform_post_id="n-1",
                author_handle="@Sama",
                caption="viral",
                platform_url="https://x.com/sama/status/n-1",
                metrics={
                    "likes": 900,
                    "replies": 20,
                    "retweets": 30,
                    "impressions": 5000,
                },
                discovered_at=dt(7),
                alerted_at=dt(7),
                alert_dismissed=True,
            ),
            m.ListeningMatch(
                id=2,
                profile_id=1,
                platform_post_id="n-2",
                author_handle="levelsio",
                caption="second",
                platform_url="https://x.com/levelsio/status/n-2",
                metrics=None,
                discovered_at=dt(8),
                alerted_at=dt(8),
            ),
            m.ListeningMatch(
                id=3,
                profile_id=3,
                platform_post_id="n-1",
                author_handle="sama",
                caption="dup via merged profile",
                platform_url="u",
                discovered_at=dt(9),
            ),
            m.ListeningMatch(
                id=4,
                profile_id=1,
                platform_post_id="n-3",
                author_handle="bad handle!!",
                caption="skip me",
                platform_url="u",
            ),
        ]
    )
    s.add_all(
        [
            m.PollConfig(
                id=1,
                profile_id=1,
                interval_minutes=15,
                is_active=True,
                last_polled_at=dt(8),
            ),
            m.PollConfig(id=2, profile_id=3, interval_minutes=5),
            m.PollConfig(id=3, profile_id=2, interval_minutes=99999),
        ]
    )
    s.add_all(
        [
            m.ChatMessage(
                id=1, profile_id=1, role=m.ChatRole.USER, content="hi", created_at=dt(2)
            ),
            m.ChatMessage(
                id=2,
                profile_id=1,
                role=m.ChatRole.ASSISTANT,
                content="hello",
                tool_calls=[{"id": "c1", "name": "get_posts"}],
                tools_used=["get_posts"],
                created_at=dt(2, 13),
            ),
            m.ChatMessage(
                id=3,
                profile_id=1,
                role=m.ChatRole.TOOL,
                content="{}",
                tool_name="get_posts",
                reason="needed",
                created_at=dt(2, 14),
            ),
            m.ChatMessage(
                id=4, profile_id=3, role=m.ChatRole.USER, content="from merged profile"
            ),
            m.ChatMessage(id=5, profile_id=4, role=m.ChatRole.USER, content="orphan"),
        ]
    )
