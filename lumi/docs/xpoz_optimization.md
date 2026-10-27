# Xpoz credit optimization plan (+ cross-platform @-handle search)

> Written 2026-10-17 from **verified sources**: Xpoz pricing page, the live OpenAPI spec
> (`https://api.xpoz.ai/openapi.json`), and two live probe queries against both API keys.
> No guesses — anything unverified is marked as such.

---

## 0. PFM HOLD (read first)

**PFM's API has expired (JWT/token no longer valid — feed endpoint 401s). HOLD all PFM-dependent work
until the key is renewed.** Concretely:

- `backfill_posts`, `_attempt_pfm_backfill`, `_ingest_pfm_feed`, `seed_demo_profiles`, `connect_account`
  are all PFM-backed and will fail or no-op. **Do not debug them as if they were broken code — the
  credential is dead.**
- The Xpoz own-handle fallback (`_ingest_xpoz_user_posts`, `analytics.py:84`) is the working
  own-posts path in the meantime. It burns Xpoz credits (2/query) — see §3.
- When PFM is renewed: re-run `uv run alembic upgrade head` check is NOT needed (schema unchanged);
  just re-verify `/pfm/callback` and one `backfill_posts` run.

---

## 1. The Free plan — verified facts (and what "1 keyword search" actually meant)

From `https://xpoz.ai/pricing` + the OpenAPI spec, checked 2026-10-17:

| Fact | Value |
|---|---|
| Free plan credits | **500, one-time — never refreshes** (hard stop at 0) |
| "1 tracked keyword/user" | **1 continuous-monitoring slot**, NOT a per-query limit |
| X/Reddit query cost | **2 credits per query** (rows returned are free) |
| TikTok query cost | 5 credits/query |
| Instagram query cost | 12 credits/query |
| Pro (for reference) | $16/mo → 7,500 credits/mo, 3 tracked slots |

**The confusion, resolved:** "1 keyword search per account" on the Free plan refers to the
*tracked-keyword registry* — Xpoz continuously collects posts matching 1 keyword or from 1 tracked
account and makes them available via stored-data endpoints. It is a monitoring slot, not a query cap.
**Ad-hoc live queries (`/api/data/twitter/posts/live`, `/api/data/twitter/users/live`) accept any
keyword, changed per call.** The LLM can absolutely rewrite keywords every search.

**So yes — the only real bottleneck is usage credits.** ~500 credits ≈ **250 X queries** total on the
Free plan. We've used about half → roughly **125 queries left** on key 1. A second working key
(`XPOZ_API_KEY_2`) is now in `.env` — if it's a separate account, that's up to ~125 more.

**Verified capabilities (probed live, 4 credits total spent):**

- `GET /api/data/twitter/users/live?q=<query>` — **user search works on both keys.** Returns up to 20
  users with `username`, `name`, `profileImageUrl`, `followersCount`, verified flags, etc. This is the
  endpoint the @-handle bar is built on.
- **Trial keys cannot use it** (403 `TrialForbidden` in the spec) — ours are not trial keys.
- ⚠️ **`/api/plan` and `/api/usage` require a dashboard session cookie, not an access key.** We cannot
  poll our remaining credits programmatically with what we have. **Client-side counting is the only
  credit meter available** — every optimization below therefore counts calls itself.

---

## 2. Where Xpoz credits are spent today (burn inventory)

| Call site | Endpoint | Cost | Trigger |
|---|---|---|---|
| `check_niche_trends` (`tools/listening.py:146`) | user-live posts × N handles | 2 × handles (**10** for the default 5) | agent tool / `POST /trends/scan` |
| `discover_and_extract_niche_frameworks` (`tools/listening.py:250`) | posts/live search | 2/run | agent tool |
| `_ingest_xpoz_user_posts` (`services/analytics.py:84`) | user-live posts, paginated | 2/page | `get_analytics` when a profile has **zero** local posts (PFM-dead world: the only own-posts path) |
| `@`-handle bar live search (new, MVP) | users/live search | 2/miss | autocomplete cache miss only |

One X Twitter query = 2 credits ≈ **$0.0043** at Pro pricing ($16/7,500). The Free plan is a sunk
500 — the goal is to make it last, not to optimize dollars.

---

## 3. Optimization plan (ordered by savings)

### 3.1 Cache-first everywhere (the big one — already started, now extended)

Every Xpoz response is persisted and reused before any new query is considered:

1. **Own posts** — already in Postgres (`posts`, `user_activity`, `metric_snapshots`); the Xpoz
   fallback only fires when a profile has zero rows. ✅ landed
2. **Peer/niche posts** — land in `listening_matches` + Chroma `peer_posts`. Before any new
   `check_niche_trends` handle fetch, reuse rows fresher than `PEER_CACHE_TTL_HOURS=12`. (Prompt 1
   decision — keep it.)
3. **Handle search (new)** — Chroma collections `handle_cache` + `handle_mappings` in the dedicated
   MVP database (`MVP_CHROMA_*` env vars, database `Onscript` — deliberately isolated from the main
   app's `CHROMA_*` so the voice-corpus storage is never repointed). Every search saves its query
   **and** results; every handle *pulled* (all results of a live query — pfp, name, followers) or
   *selected* is remembered permanently in `handle_mappings`, so the handle DB expands with every
   search. Cached searches stay fresh for `MVP_CACHE_TTL_MINUTES` (default 60) — stale entries
   trigger a budget-guarded real-time re-query instead of serving frozen results.
   **Implemented in the MVP (`mvp/handle_search/`)** — §6.

### 3.2 Prefix-chain reuse (typing ka → kar → karp = ONE query, not three)

Autocomplete naturally produces nested prefixes. The handle-search server checks the cache for any
stored query that is a **prefix of** (broader → filter down) or **prefixed by** (narrower → superset)
the current input, and re-filters locally instead of re-querying Xpoz. A user typing a 6-character
handle costs **at most 2 credits**, typically 0.

### 3.3 Hard guards on every live path

- **Debounce 300 ms client-side, minimum 2 characters** (MVP ships both).
- **Per-session budget**: `MVP_XPOZ_BUDGET` (default 10 live searches = 20 credits per server
  session). Exhausted → cache/db only, honest `"live budget used"` flag in the response.
- **Key rotation**: `XPOZ_API_KEY` → on 401/402/403 rotate to `XPOZ_API_KEY_2`. Both verified live.
- **Instrumentation**: `/api/handles/stats` exposes queries-this-session; every Xpoz call is logged
  with its route label. For the main app, a shared `xpoz_call_count` counter should eventually feed
  the same meter (follow-up, not MVP).

### 3.4 Jev as the cheap gate (the "maybe with jev" part)

Jev/TypeSafe costs **$0.042/MTok** ≈ $0.00006 per ~1.5k-token call — roughly **70× cheaper than one
Xpoz query**. Spend Jev to *avoid* Xpoz, never the reverse:

1. **Cache-adequacy judge** (planned): before a live handle query, one Jev call asks "do these cached
   handles answer this query?" — if yes, skip Xpoz entirely. Also applies to peer/niche re-scans.
2. **Result re-ranker** (planned): one batched Jev call ranks/filters a merged cache+live result set
   (never per-item calls).
3. **Query expander** (planned): Jev proposes 2–3 alternate keyword phrasings for niche searches so a
   dead first query doesn't cascade into three blind Xpoz retries.
4. **Already live**: the spike-alert backstop (`SPIKE_JEV_LIKE_FLOOR = 50`, `tools/listening.py:15-21`)
   uses Jev instead of extra metric fetches.

Rule of thumb: **one Jev call to decide > one Xpoz call to check.**

### 3.5 What we deliberately do NOT do

- Xpoz's tracked-keyword registry / crawl CSV (the "1 slot" feature) — spec rejected it for v1
  (`.agents/external-services.md`); our polling design doesn't need it and it would lock the single
  Free slot to one keyword.
- No speculative prefetching. Every live query must be triggered by an actual user/agent need.

---

## 4. Next-step recommendation (credits)

1. Treat the remaining ~125 credits on key 1 as **demo ammunition**: @-bar demos (cache-first — most
   demos cost 0), one `check_niche_trends` run, nothing else until the niche/peer Prompts 1–3 get
   their own budget go-ahead (`XPOZ_RUN_CREDIT_BUDGET` must be wired **before** those pipelines).
2. If real usage starts: Pro is $16/7,500 credits (≈ 3,750 X queries) — cheap insurance.
3. Keep the second key as overflow only; rotation happens automatically on auth failure.

---

## 5. Cross-platform tagging — LANDED 2026-10-25 ✅

> **Shipped:** the `platforms` CSV param now runs through the whole stack —
> `GET /api/handles/search?platforms=x,instagram,tiktok,reddit,linkedin` (and the
> `/handles/*` shim + PromptBar + standalone bar pill-row selector). Per-platform
> fan-out hits `/api/data/<platform>/users/live` with the spec-verified params
> (`q` for X/Reddit, `name` for IG/TikTok) and normalizes each response shape
> (IG `fullName/profilePicUrl/followerCount`, TikTok `nickname/avatar/followerCount`,
> Reddit → NULL display name/followers). The budget is now counted in **credits**
> (`MVP_XPOZ_BUDGET`, default 100), each platform's price charged on its query, and
> the fan-out stops honestly when the next platform's cost won't fit. Cache keys are
> `platform:query`, the local-db layer stays X-only, and every result row carries
> `platform` (legacy rows default `x`). Tests: `legacy/tests/test_handle_search_platforms.py`.

Xpoz also exposes **user search for other platforms** (verified in the OpenAPI spec):
`/api/data/instagram/users/live` (**12 credits**), `/api/data/tiktok/users/live` (**5**),
`/api/data/reddit/users/live` (**2**). Same cache-first bar, one `platform` param:

- **Instagram at 12 credits/query makes the cache non-negotiable** — a single uncached IG search
  costs as much as 6 X searches. Live IG search stays behind the same budget guard.
  (**Done:** credit-based budget; a mixed X+Reddit+TikTok+IG fan-out costs 21 credits on a cold
  cache, then 0 on repeat.)
- **LinkedIn has no Xpoz endpoint** (the spec covers X, Instagram, Reddit, TikTok only) — it stays
  in the selector as an honest db/remembered-only platform (`platform_reasons.linkedin =
  "unsupported"`, 0 credits, never a fabricated live source).
- The `social_handles` table (§7) is platform-native from day one (`platform` column +
  `unique(platform, handle_lower)`), so cross-platform identity mapping is rows, not a redesign.
- Same-person linking across platforms (X @handle ↔ IG @handle) is a **phase-2** feature: manual /
  profile-link evidence first, never auto-merged on name similarity alone (that's a wrong-tagging
  machine). Jev can rank merge *candidates*; a human or a hard signal confirms.

---

## 6. The @-handle search MVP (built)

**Location: `lumi/mvp/handle_search/` — born as a standalone side project (still runnable on its own at :8010); wired into the main app 2026-10-21.** The main backend mounts the same handlers under `/handles/search|saved|select|stats` via `legacy/app/routers/handles.py` (a thin delegation shim — zero logic duplication, one API base for the chat frontend), and the chat composer's typed `@` menu (`PromptBar.tsx`) is the real search UI: instant 0-credit paint from the saved-handles snapshot + a 300 ms-debounced refine, picking inserts `@handle ` (no auto-send) and POSTs `/handles/select`; sending then follows prompt rule 13 (`save_user_request` → `check_niche_trends`).

```
mvp/handle_search/
├── server.py          # FastAPI app (port 8010)
└── static/index.html  # the text bar UI (vanilla JS, no build step)
```

**Run it:**

```
cd lumi
uv run uvicorn mvp.handle_search.server:app --port 8010
# open http://127.0.0.1:8010
```

**How a keystroke flows (cache-first, credit-aware, but never locked to cache):**

1. User types `@` in the bar → dropdown arms at **2+ chars**. From the very first keystroke the
   client prefix-filters its in-browser snapshot of saved handles (`GET /api/handles/saved`,
   loaded at page load, refreshed after each full search and each selection) — **0 ms, no
   request, no credits** — so already-known handles paint instantly. The 300 ms-debounced full
   pipeline below then runs once and refines the same dropdown; if the snapshot had nothing, a
   **breathing skeleton** (a gentle in/out pulse) shows while the real search runs — never a
   false "no matches" — and a small breathing dot rides under db-served rows until the
   refinement lands.
   The client also captures the **up-to-3 words typed before the `@`** and sends them as
   `context`, used only to re-rank results (never sent to Xpoz — see step 5).
2. Server checks, in order — **all zero-credit**:
   - **local DB** (`lumi.db` read-only): handles from `listening_matches.author_handle` +
     `profiles.handle`, prefix match;
   - **Chroma `handle_mappings`**: every handle ever *pulled, selected, or fed by a main-app
     search* (permanent memory);
   - **Chroma `handle_cache`**: results of previous searches, with **prefix-chain reuse**
     (§3.2) so ka→kar→karp costs one query, not three — **while the entries are fresh**
     (`MVP_CACHE_TTL_MINUTES`, default 60).
   The first two layers are a **head start, not the answer**: their rows merge into the results
   (and paint instantly client-side) but never gate what follows.
3. Live fires when the cache has **no fresh answer** — either nothing at all, or only
   **stale** cached results (older than the TTL → real-time refresh, so the bar is never
   frozen to an old cache). The handle DB deliberately does *not* count: without that rule,
   `@ateh` would show only the one Ateh saved in the db instead of the actual people currently
   on X — the db must add to results, never replace them. Gated by live-enabled + session
   budget → Xpoz `users/live` (2 credits, key rotation on auth failure). A fresh *empty* cache
   entry (negative cache) still never re-burns credits, and when live is off or the budget is
   spent the db/mappings rows remain the free fallback. Results are saved back to
   `handle_cache` — **the next identical/prefix search within the TTL is free**.
4. **Every pulled handle moves into `handle_mappings` automatically** — all results of every
   live pull (pfp, display name, follower count), *not just the one the user selects* — so the
   handle DB keeps expanding with every search. Cache-only results not yet remembered are
   persisted the same way. Each row records `origin: live | cache | selected | niche` and a
   timestamp. The **main app feeds the same store** (`legacy/app/services/handle_db.py`, add-if-absent,
   never raises): `check_niche_trends` persists every tracked account (bounded enrichment —
   picture/name/followers via the verified user search for handles the store has never seen,
   exact username match only, ≤2 credits each, `HANDLE_DB_ENRICH_LIMIT` per scan, `0` off) plus
   every author of every returned post; `discover_and_extract_niche_frameworks` persists every
   search-result author handle-only (unbounded enrichment would burn dozens of credits; the bar
   falls back to unavatar for the picture and followers stay NULL — never fabricated).
5. Results merge & dedupe, each tagged `source: db | cache | live` and shown with avatar (Xpoz
   `profileImageUrl`, with an `unavatar.io` fallback for cache/db hits), display name, follower
   count. Ranking: within each group, exact-handle match first, then a **context boost** (up to 3 words typed before
   the `@` — they rank merged results but are never added to the Xpoz query, since Lucene AND
   would kill the result set), then followers desc (local-db handles lead their group). The list is then a **half-and-half mix by where each handle came from on this search**: about half the slots go to the **saved half** — everything served from memory (local db / remembered / past-search cache), with local-db handles such as `@AtehOfficial` leading it — and half to the **live half**, what a fresh Xpoz pull just returned; a side short of half hands its leftover slots to the other so the list still fills to ten, and the exact handle you typed stays at the very top. Because the split is by origin, a memory-served handle can never crowd a fresh-pull one out of view — they sit in different halves. A stale refresh replaces the stale copy with
   the fresh pull (`refreshed: true` in the response).
6. **Selection goes to the backend** — `POST /api/handles/select` stores the handle in
   `handle_mappings` (the "rememberance" layer, `origin: selected`) and returns an ack. Wiring
   that selection into the main chat/composer is explicitly **out of MVP scope** (per spec:
   don't plan the backend passing).

**Endpoints:** `GET /` (the bar), `GET /api/handles/search` (accepts `context` for ranking),
`GET /api/handles/saved` (instant-suggest snapshot: db ∪ remembered, deduped, followers first),
`POST /api/handles/select`, `GET /api/handles/stats` (session credit meter + combined
`saved_handles` count + collection sizes + per-origin handle counts + cache TTL).

**Env vars used** (all in `.env`, never in code): `XPOZ_API_KEY`, `XPOZ_API_KEY_2` (rotation),
`MVP_CHROMA_API_KEY`, `MVP_CHROMA_TENANT`, `MVP_CHROMA_DATABASE` (the `Onscript` Chroma database),
`MVP_XPOZ_BUDGET` (optional, default 10), `MVP_XPOZ_LIVE` (optional, default on),
`MVP_CACHE_TTL_MINUTES` (optional, default 60), `HANDLE_DB_ENRICH_LIMIT` (optional, default 6 —
new scanned handles enriched per scan; `0` disables), `HANDLE_SEARCH_DB` (optional, defaults to
`lumi.db`).

**Tests:** `legacy/tests/test_handle_search_mvp.py` — Xpoz fully mocked; covers db-as-head-start merge
(db hits never gate live), the free db fallback when live is off, live-on-miss, cache reuse,
prefix-chain reuse, budget exhaustion, key rotation, handle remembering, auto-persistence of
every live pull (pfp + followers, without selection), and the TTL real-time refresh (stale →
re-query, fresh negative cache → no re-burn, stale + budget spent → honest fallback).
`legacy/tests/test_handle_db.py` — the main-app side: MVP-compatible row shape, add-if-absent,
enrichment rules (exact match only, cap, off), never-raises, and both listening tools wired
(every scanned handle + author persisted; a scan survives a handle-DB failure). Both suites
must stay green with **no network**.

---

## 7. In-depth plan: the `handles` column ("where do we put the handles?")

**Decision: a dedicated `social_handles` table — not a JSON column on `profiles`.** A JSON column
fails every real need: no `UNIQUE` (the dedup that makes the cache trustworthy), no per-handle
metadata (avatar, follower snapshot, `last_seen_at`), no cross-profile lookup ("which profiles listen
to @karpathy?"), no clean multi-platform identity mapping, and every read is a full-row parse.
Postgres gives us a prefix index for free. The MVP's Chroma `handle_mappings` is the prototype of
this table — same fields, richer storage — so adoption is a copy, not a rethink.

### 7.1 Schema (next migration, after `b7d2e5f8a3c1`)

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `platform` | VARCHAR NOT NULL default `'x'` | `x` / `instagram` / `tiktok` / `reddit` |
| `handle` | VARCHAR NOT NULL | canonical case as seen |
| `handle_lower` | VARCHAR NOT NULL | normalized; matching + uniqueness live here |
| `display_name` | VARCHAR NULL | |
| `avatar_url` | VARCHAR NULL | NULL → UI falls back to `unavatar.io/<platform>/<handle>` |
| `followers` | INTEGER NULL | **NULL when unknown — never fabricate 0** (repo invariant) |
| `identity_profile_id` | INT NULL FK→profiles | set when the handle is one of *our* connected accounts |
| `source` | VARCHAR NOT NULL | `'xpoz_users'` \| `'mvp_selection'` \| `'listening_ingest'` \| `'manual'` |
| `first_seen_at` | UTCDateTime NOT NULL | app-side default `now(UTC)` |
| `last_seen_at` | UTCDateTime NOT NULL | bumped on every re-encounter |

Constraints: `UNIQUE(platform, handle_lower)`; index on `handle_lower` (btree serves prefix
`LIKE 'q%'` autocompletes at our scale).

### 7.2 Writers

- MVP `POST /api/handles/select` (phase 2: writes the table directly instead of/in addition to Chroma)
- `check_niche_trends` — every author it ingests
- `_ingest_xpoz_user_posts` / PFM callback / `seed_demo_profiles` — our own connected handles
  (`identity_profile_id` set)
- future: `@mention` extraction from `posts`/`user_activity` captions (regex on caption text)

### 7.3 Readers

- @-handle bar autocomplete (`WHERE platform=? AND handle_lower LIKE q||'%' ORDER BY followers NULLS LAST LIMIT 8`)
- agent tools: resolve an `@mention` in a caption → identity + prior context without an API call
- cross-platform tagging: `GROUP BY identity` once multi-platform rows exist
- niche peer discovery: candidate handles already vetted/seen (feeds `PeerSeed`)

### 7.4 Rollout steps (each independently verifiable)

1. `legacy/app/models/handles.py` + Alembic revision (`down_revision='b7d2e5f8a3c1'`), copy-tested up/down.
2. `scripts/backfill_handles.py` — seed from `listening_matches.author_handle` (9 distinct today),
   `profiles.handle` (2), and `@mention` regex over `posts`/`user_activity` captions. Idempotent.
3. Writers 1–3 above, each behind the same upsert-by-unique-key pattern.
4. Point the MVP's `/api/handles/select` + `/api/handles/search` at the table (Chroma stays as the
   semantic/keyword index; Postgres is the source of truth — same invariant as the main app).
5. Tests: uniqueness, backfill idempotency, autocomplete prefix query, NULL-follower honesty.

---

## 8. Checklist

- [x] Verified plan/credits/keyword facts (pricing page + OpenAPI + live probes)
- [x] New key + Chroma credentials stored in `.env` only
- [x] @-handle search MVP built + tested (`mvp/handle_search/`, `legacy/tests/test_handle_search_mvp.py`)
- [ ] Jev cache-adequacy gate (after MVP validation — needs a $ decision? no: Jev is ~free; just build)
- [ ] `xpoz_call_count` meter in the main app's `XpozClient`
- [ ] `social_handles` migration + backfill (§7) — **gated on your go** (schema change)
- [ ] PFM renewal → un-hold §0 items
