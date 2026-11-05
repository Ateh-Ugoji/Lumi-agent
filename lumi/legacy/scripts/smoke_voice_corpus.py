import asyncio

from sqlmodel import select

from app.database import session_scope
from app.models.post import Post
from app.models.profile import Profile
from app.services.voice_corpus import retrieve_extraction_sample, sync_profile_corpus


async def main() -> None:
    async with session_scope() as session:
        profiles = (await session.exec(select(Profile))).all()
        print("profiles:", [(p.id, p.handle) for p in profiles])
        for p in profiles:
            posts = (await session.exec(select(Post).where(Post.profile_id == p.id))).all()
            print(f"profile {p.id} ({p.handle}): {len(posts)} posts in DB")
            n = await sync_profile_corpus(p.id)
            print(f"  indexed into corpus: {n}")
            sample = retrieve_extraction_sample(p.id, limit=10)
            if sample:
                first = sample[0]["caption"][:60]
                print(f"  diverse sample: {len(sample)} captions, first={first!r}")
            else:
                print("  diverse sample: none (corpus empty/unavailable)")


if __name__ == "__main__":
    asyncio.run(main())
