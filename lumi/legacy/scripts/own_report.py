"""Own-account data-quality report — profile-extract fixes at a glance.

Prints, for one profile: ingestion mix (originals / self-replies / RTs via
posts + user_activity), NULL-vs-zero metric state, snapshot milestone
coverage, deletion-suspect count, the profile baseline, and the own lift
table. READ-ONLY: never writes (compute_own_lift runs with
persist_baseline=False).

Usage (from the lumi/ directory):
    uv run python scripts/own_report.py            # every profile with posts
    uv run python scripts/own_report.py 2          # just profile 2
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import func, select

from app.analysis.own_lift import compute_own_lift
from app.database import session_scope
from app.models.activity import UserActivity
from app.models.post import MetricSnapshot, Post
from app.models.profile import Profile, ProfileBaseline


async def report_profile(profile_id: int) -> None:
    async with session_scope() as session:
        profile = await session.get(Profile, profile_id)
        if profile is None:
            print(f"profile {profile_id}: NOT FOUND")
            return

        posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()
        post_ids = [p.id for p in posts if p.id is not None]
        snapshots: list[MetricSnapshot] = []
        if post_ids:
            snapshots = (
                await session.exec(
                    select(MetricSnapshot).where(MetricSnapshot.post_id.in_(post_ids))
                )
            ).all()

        activity_rows = (
            await session.exec(select(UserActivity).where(UserActivity.profile_id == profile_id))
        ).all()

        latest_baseline = (
            await session.exec(
                select(ProfileBaseline)
                .where(ProfileBaseline.profile_id == profile_id)
                .order_by(ProfileBaseline.computed_at.desc())
            )
        ).first()

    kinds: dict[str, int] = {}
    for p in posts:
        kinds[p.kind or "original"] = kinds.get(p.kind or "original", 0) + 1

    act_kinds: dict[str, int] = {}
    for a in activity_rows:
        act_kinds[a.kind] = act_kinds.get(a.kind, 0) + 1

    n_null_views = sum(1 for s in snapshots if s.views is None)
    n_null_any = sum(
        1 for s in snapshots if None in (s.views, s.likes, s.comments, s.shares)
    )
    n_with_age = sum(1 for s in snapshots if s.age_hours is not None)
    n_zero_all = sum(
        1
        for s in snapshots
        if (s.views, s.likes, s.comments, s.shares) == (0, 0, 0, 0)
    )
    truncated = sum(1 for p in posts if p.text_truncated)
    suspects = sum(1 for p in posts if p.is_deleted_suspect)

    print(f"== profile {profile_id}: @{profile.handle} ({profile.name}) ==")
    print(
        f"  timezone: {profile.timezone or '-'} (source: {profile.timezone_source or '-'})"
    )
    print(f"  posts table: {len(posts)} rows — {kinds or '{}'}")
    print(f"  user_activity: {len(activity_rows)} rows — {act_kinds or '{}'}")
    print(f"  truncated flagged: {truncated}   deleted suspects: {suspects}")
    print(f"  metric_snapshots: {len(snapshots)}")
    print(f"    with age_hours: {n_with_age}   any-NULL metric: {n_null_any}")
    print(f"    NULL views (Rule A/B fixed): {n_null_views}   still all-zero: {n_zero_all}")
    if latest_baseline is not None:
        print(
            "  baseline row: "
            f"n={latest_baseline.n_posts} median_views={latest_baseline.median_views:.0f} "
            f"p75={latest_baseline.p75_views:.0f} median_eng={latest_baseline.median_engagement:.0f} "
            f"reliable={latest_baseline.baseline_reliable} "
            f"computed_at={latest_baseline.computed_at.isoformat(timespec='seconds')}"
        )
    else:
        print("  baseline row: none yet (run bootstrap or scripts/own_report.py)")

    lift = await compute_own_lift(profile_id, persist_baseline=False)
    print(f"  own lift: status={lift['status']}" + (f" — {lift.get('reason')}" if lift.get("reason") else ""))
    b = lift.get("baseline") or {}
    print(
        f"    baseline (computed): n={b.get('n_posts')} median_views={b.get('median_views', 0):.0f} "
        f"p75={b.get('p75_views', 0):.0f} reliable={b.get('baseline_reliable')}"
    )
    print(f"    eligible posts: {lift.get('n_eligible', 0)}   winners: {lift.get('n_winners', 0)}")
    reported = [r for r in lift.get("lift_rows", []) if r.get("status") == "reported"]
    for row in reported:
        print(
            f"    reported: {row['dimension']}={row['value']!r} "
            f"lift={row['lift']} (winners {row['n_winners']} vs baseline {row['n_baseline']})"
        )
    if not reported:
        print("    reported rows: none (dimensions carry computed values only until tagging lands)")
    print()


async def main() -> None:
    async with session_scope() as session:
        if len(sys.argv) > 1:
            ids = [int(sys.argv[1])]
        else:
            ids = list(
                (
                    await session.exec(
                        select(Profile.id)
                        .join(Post, Post.profile_id == Profile.id)
                        .group_by(Profile.id)
                        .order_by(func.count(Post.id).desc())
                    )
                ).all()
            )
    if not ids:
        print("no profiles with posts found")
        return
    for pid in ids:
        await report_profile(pid)


if __name__ == "__main__":
    asyncio.run(main())
