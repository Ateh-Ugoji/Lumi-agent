"""One-off cleanup: remove retweets/replies from posts + rebuild voice corpora.

Usage: uv run python scripts/cleanup_authentic_posts.py
"""

import asyncio

from sqlmodel import select

from app.database import session_scope
from app.models.post import MetricSnapshot, Post
from app.services.pfm import is_authentic_original
from app.services.voice_corpus import clear_profile_corpus, sync_profile_corpus


async def main() -> None:
    async with session_scope() as session:
        profiles = (await session.exec(select(Post.profile_id).distinct())).all()
        for profile_id in profiles:
            posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()
            polluted = [p for p in posts if not is_authentic_original(p.caption)]
            for p in polluted:
                snaps = (
                    await session.exec(select(MetricSnapshot).where(MetricSnapshot.post_id == p.id))
                ).all()
                for s in snaps:
                    await session.delete(s)
                await session.delete(p)
            await session.commit()
            print(f"profile {profile_id}: {len(posts)} posts, removed {len(polluted)} polluted")

    for profile_id in profiles:
        clear_profile_corpus(profile_id)
        n = await sync_profile_corpus(profile_id)
        print(f"profile {profile_id}: corpus rebuilt with {n} authentic posts")


if __name__ == "__main__":
    asyncio.run(main())
