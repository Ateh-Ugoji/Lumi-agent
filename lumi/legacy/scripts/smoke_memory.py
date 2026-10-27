"""Live smoke for Phase 2 + 3: framework index/query, remember/recall, memory.md."""

import asyncio

from app.services.chroma import (
    AGENT_MEMORY,
    PEER_FRAMEWORKS,
    PEER_POSTS,
    get_collection,
)
from app.services.framework_corpus import (
    query_frameworks,
    query_peer_posts,
    sync_frameworks_from_db,
)
from app.services.memory import (
    MEMORY_PATH,
    get_profile_summary,
    recall,
    remember,
    upsert_profile_summary,
)


async def main() -> None:
    print("== 1. Chroma collections ==")
    for name in (PEER_FRAMEWORKS, PEER_POSTS, AGENT_MEMORY):
        col = get_collection(name)
        n = len(col.get(limit=300).get("ids") or []) if col else -1
        print(f"  {name}: {'DOWN' if col is None else f'{n} docs'}")

    print("== 2. Framework DB backfill ==")
    indexed = await sync_frameworks_from_db()
    print(f"  sync_frameworks_from_db -> {indexed} indexed")

    print("== 3. Framework queries (profile 2) ==")
    fw = query_frameworks(2, "what content framework works for building in public")
    posts = query_peer_posts(2, "launch hook viral post")
    print(f"  frameworks hits: {len(fw)}")
    if fw:
        print(f"    first: id={fw[0]['id']} dist={fw[0]['distance']:.3f}")
        print(f"    doc[:110]={fw[0]['text'][:110]!r}")
    print(f"  peer_posts hits: {len(posts)}")

    print("== 4. remember / recall ==")
    res = remember(2, "smoke test fact: prefers hooks under 12 words", kind="preference")
    print(f"  remember -> {res}")
    res2 = remember(2, "smoke test fact: prefers hooks under 12 words", kind="preference")
    print(f"  dedupe   -> {res2}")
    out = recall(2, "posting hook preference")
    print(f"  recall found={out.get('found')} n={len(out.get('memories', []))}")
    for m in out.get("memories", [])[:2]:
        print(f"    - {m['text']!r} (dist={m.get('distance'):.3f})")

    print("== 5. memory.md ==")
    upsert_profile_summary(2, "- ships daily\n- builder in Lagos", handle="AtehOfficial")
    print(f"  summary(2) = {get_profile_summary(2)!r}")
    print(f"  file at {MEMORY_PATH} exists={MEMORY_PATH.exists()}")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
