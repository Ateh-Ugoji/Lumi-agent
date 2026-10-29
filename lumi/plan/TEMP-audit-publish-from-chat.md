# TEMP audit — "Post for Me from natural language" → direct providers

Status: **audit + revised plan, no code yet.** Written 2026-10-28 on branch `lumi-orquestador`.
Purpose: re-plan the chat-publishing feature now that we hold direct API credentials for
LinkedIn, X and TikTok (found in the Onscript backend env), so Post for Me is no longer needed
as the router.

---

## 1. The original plan (as handed over)

> Post for Me from natural language. Goal: in the Lumi chat the user can publish a post, read
> their views, and ask which post is the most viewed. Decisions already taken: **Post for Me for
> everything (publish, read posts, metrics), text only, publish now only.** Steps: a
> `publish_post` agent tool (preview first, publish only after the user confirms), **route
> publishing through Post for Me**, store more metrics from the feed, a `top_posts` tool that
> ranks in SQL, and auto-refresh of old data.

## 2. What the audit found (verified in this repo, file:line)

| # | Finding | Evidence |
|---|---|---|
| 1 | **Publishing is already native — PFM was never the publisher.** The REST path routes `facebook→meta`, `linkedin→linkedin`, `x→x` directly. The docstring says Instagram/TikTok "would go through Post for Me, whose posting call is not built". | `apps/connections/publish_api.py:43`, `:1-7` |
| 2 | **Reading own posts is split (updated same day after `a534dec`/R3):** a Facebook profile with a connected Page goes `backfill_posts` → `DjangoOwnPostSync.sync_own_posts` → `collect_meta_posts` (native Meta); every other network goes → `PfmClient.get_account_feed_page` → `map_pfm_item` (PFM, token expired). | `apps/intelligence/tasks.py:105`, `apps/connections/own_post_sync.py:75-99`, `apps/connections/own_posts.py` |
| 3 | **PFM is dead in this environment right now.** `check_keys`: `FALLA pfm — PFM rechazó el token (vencido o inválido)`. The plan's "read from the feed" cannot work today regardless of keys. | `manage.py check_keys`, run 2026-10-28 |
| 4 | ~~Meta's read side has no caller~~ **Superseded the same day by `a534dec` (R3):** `collect_meta_posts` now calls `fetch_posts`/`fetch_metrics` in production for connected Facebook Pages (metrics bounded to the newest 20 per sync). | `own_post_sync.py:75`, `own_posts.py:98,109`; `providers/meta.py:240,278` |
| 5 | **X reads were deliberately kept off the native API** (per-read pricing): "X charges per resource read, so Lumi reads X through Xpoz." | `providers/x.py:1-9`, `can_read_posts=False` (`:84`) |
| 6 | **LinkedIn publish works; reading is scope-gated** (`r_member_social`, restricted) — account goes `limited` without it. | `providers/linkedin.py:92-95,201-211` |
| 7 | **TikTok has no native provider at all** — only appears in `PFM_PLATFORMS`. | `providers/` (no tiktok.py), `connect_links.py:25` |
| 8 | **The local `.env` had zero provider credentials** — `meta/linkedin/x/google` all `OMITIDA (falta …)`. | `check_keys` |
| 9 | **The agent has no publish tool.** Tools are built in `lumi_ai/tools/*` and assembled in `apps/intelligence/wiring.py:228-248`; nothing calls the publish service. | `lumi_ai/tools/registry.py` |
| 10 | **`get_analytics` already ranks `top_posts`, but in Python** over ≤500 posts — the plan's "rank in SQL" would move this into a query that scales and answers "which post is most viewed" directly. | `lumi_ai/tools/data.py:96-131` |
| 11 | **The two-times write pattern already exists** (`dry_run` + `confirm` + `Idempotency-Key`, and MCP's propose→confirm pending writes) — the agent tool should reuse it, not invent a new one. | `publish_api.py`, `apps/connections/mcp/gateway.py`, plan D6 |
| 12 | Routing decision "provider per platform" is **written in three places** (`PROVIDER_FOR_PLATFORM`, `NATIVE_PROVIDER`, `PFM_PLATFORMS`) — the drop-PFM change would make it four without the single routes table. | `publish_api.py:43`, `connect_links.py:24-25`, `ingest.py:34` |

## 3. Audit verdict, step by step

| Original step | Verdict | Why |
|---|---|---|
| `publish_post` agent tool (preview → confirm) | **KEEP — first value** | Nothing in the plan depends on PFM: the REST publish path is already native per provider. |
| Route publishing through Post for Me | **DROP — obsolete & never built** | Publish is native since CONNECT delivered T6; PFM's posting call doesn't exist and its token is expired. Routing through PFM would be *new* work to replace something that already works. |
| Store more metrics from the feed (PFM feed) | **REPLACE — native sources** | Meta: `fetch_metrics` exists, needs a caller. LinkedIn: `fetch_posts` + member posts API when scope present. X: keep **Xpoz** for reads (deliberate pricing decision, x.py:5) — native X reads only as an opt-in fallback. TikTok: new provider (P6). |
| `top_posts` tool ranking in SQL | **KEEP — done (`e7bf9d1`)** | Independent of PFM; landed as the SQL tool in `lumi_ai/tools/data.py`. |
| Auto-refresh of old data | **KEEP** | Driven by provider `fetch_metrics`, not the PFM feed, after P2. |

**Core change: the plan's spine moves from "PFM does everything" to "each provider does its own
publish + read, one routes table decides who serves which platform" — which is exactly decision
D3 of `PLAN_REDES-SOCIALES.md` (single routes table) pulled forward.**

## 4. Revised plan (ordered, protocol-compliant)

Same protocol as the other plans: audit → plan → execute; per task an owner, deliverable and
verification; docs (`AGENTS.md`, `docs/flow-map.md`, `docs/API_KEYS.md`, `.env.example`) updated
in the same change as the code.

### P0. Credentials + connect-callback registration (setup, before any code)
- Put the found credentials in `lumi/.env` (they live only in the env — AGENTS.md secrets rule):
  `META_APP_ID/SECRET` (from the Onscript `FACEBOOK_APP_ID/SECRET`), `LINKEDIN_CLIENT_ID/SECRET`,
  `X_CLIENT_ID/SECRET` (from `TWITTER_*`), `GOOGLE_OAUTH_CLIENT_ID/SECRET`, `X_LIVE_ENABLED=true`.
  TikTok: no consumer exists yet — the values (`TIKTOK_CLIENT_ID/SECRET/APP_ID`) are staged in
  `.env` under their own names until P6.
- **External step (human):** add the redirect URI `http://localhost:3011/connections/<provider>/callback`
  (built by `config.redirect_uri`, `apps/connections/config.py:185-188`, over `FRONTEND_URL`) to
  each developer portal: X app, LinkedIn app, Meta app, Google console. Without this, connect
  fails with redirect_uri mismatch regardless of correct keys.
- **Verify:** `manage.py check_keys` → `meta/linkedin/x/google` OK (or a typed reason), `pfm`
  failure becomes irrelevant.

### P1. One routes table (`providers/routes.py`) — was R2 of PLAN_REDES-SOCIALES, pulled forward — **done 2026-10-28**
- Single owner for platform → providers-in-order + capabilities. Replaces
  `PROVIDER_FOR_PLATFORM`, `NATIVE_PROVIDER`, both `PFM_PLATFORMS`.
- **Verify:** `pytest apps/connections` green untouched; `rg "PROVIDER_FOR_PLATFORM|NATIVE_PROVIDER"`
  finds no duplicated definitions.
- **Result:** `ROUTES` maps platform → ordered `Route(provider, publish, read)`;
  `publish_api` calls `publish_provider()`, `connect_links` calls `native_provider()`
  + the derived `PFM_PLATFORMS`, `ingest` imports `PFM_PLATFORMS`. Verify run:
  `pytest apps/connections` → **877 passed, 2 skipped** (the single `test_keys`
  failure is pre-existing and `.env`-driven — stash-verified against the base
  commit, unrelated to routing); `grep` finds no duplicated definition left, only
  prose mentions. 7 new tests in `tests/test_routes.py`, including a drift check
  that compares the table against each adapter's own `capabilities()`.

### P2. Native own-posts + metrics ingestion (replaces "read from the feed")
- Extend `OwnPostSync` to dispatch per routes table: `meta.fetch_posts/fetch_metrics` (already
  implemented), `linkedin.fetch_posts` when `r_member_social` present, `x` → keep the Xpoz path
  (`_ingest_xpoz_user_posts` semantics), `instagram/tiktok` → typed `UnsupportedOperation`
  until P6. PFM moves from "the only source" to "no source" (kept only if Instagram needs it —
  see open question Q1).
- Snapshot policy stays as parity row 25 (append only when a metric changed).
- **Verify:** with PFM token absent, `backfill_posts` fills `posts` + `metric_snapshots` for a
  Meta-connected profile in tests with mock transports; real run with `LUMI_RUN_LIVE=1` and
  explicit permission.

### P3. `publish_post` agent tool (the feature itself — text only, publish now only)
- New tool in `lumi_ai/tools/account.py` (or a new `publish.py`), registered through
  `wiring.py` extra list. Two-step: **preview** (dry_run → the agent shows the exact text +
  platform + target account) then **confirm** (user says yes → call the existing
  `publish_api.publish_post` service with `confirm=true` + generated `Idempotency-Key`,
  reusing the pending-write pattern from `mcp_pending_writes` for the agent side).
- Cost tier `write`, side effect `external_write`, never cached; respects token budget of the
  prompt (measure tool tokens before/after — R6 note).
- **Verify:** unit tests with mock transport: preview publishes nothing; confirm publishes once;
  repeated confirm replays the same `PublishJob`; no-connect → typed 409 the agent explains;
  platform not served → typed unsupported, agent never invents a result.

### P4. `top_posts` tool with SQL ranking — done (`e7bf9d1`)

Landed the same day by the team: ranks by the latest non-null metric (views/likes/comments/shares)
with platform, period and top-N filters, local DB only — which supersedes the 28-day,
views-only sketch below.
- Rank by latest snapshot per post (`views DESC`, 28-day window), SQL-side, NULL-safe (a metric
  nobody reported stays null, never 0). `get_analytics` keeps its aggregates; the new tool
  answers "which of my posts is the most viewed" without shipping 500 rows to the LLM.
- **Verify:** fixture posts with differing snapshots → correct order, honest `no data` answer on
  empty profile (never fabricated).

### P5. Auto-refresh of old data
- Bounded refresh job (poller / Celery beat when T9 lands): posts whose `last_checked_at` is
  older than N hours get `fetch_metrics` from their provider; respects existing snapshot policy
  and daily caps. Same pass feeds P4.
- **Verify:** stale post gets refreshed once; fresh post untouched; provider outage → no
  partial pass marked complete (existing `finalize_pass` semantics).

### P6. TikTok provider (only because we now have its keys)
- `providers/tiktok.py` behind `TIKTOK_LIVE_ENABLED` (same pattern as X), OAuth 2.0 with
  `content.post`/`video.list` scope, `Capabilities` declares publish + metrics, env names
  `TIKTOK_CLIENT_ID/SECRET/APP_ID` (already staged in P0).
- **Verify:** capability-matrix test includes tiktok; nothing leaves the box without the flag.
- ⚠️ R1-style revalidation first: TikTok's Content Posting API has app-audit requirements for
  third-party posting — confirm against official docs before coding (same rule as Meta's map).

### P7. Docs + cleanup (ARCHITECT)
- `AGENTS.md`, `docs/flow-map.md(.html)`, `docs/API_KEYS.md`, `.env.example`, `docs/CONEXIONES.md`:
  PFM removed as a route (or demoted), new env names, redirect-URI registration step in
  `how-to-setup.md`.
- **Verify:** full suite green (except known Windows-harness failures) + `ruff` clean.

## 5. Decisions baked in (flag if you disagree)

1. **Publish: native only** (meta/linkedin/x today, tiktok after P6). PFM not used for anything new.
2. **X reads stay on Xpoz** — pricing decision already documented in `x.py`; native X reads are
   an opt-in fallback (`X_NATIVE_READ_ENABLED`) only if Xpoz ever can't answer.
3. **Text-only, publish-now-only** retained (no media, no scheduling) — matches existing
   `PublishDraft` (text + link).
4. **Write flags:** `X_LIVE_ENABLED=true` locally so the flow is testable; production still needs
   the same deliberate switch (costs real money per post: $0.015/post, $0.20 with link).

## 6. Open questions

- **Q1 (Instagram):** PFM was the only route for Instagram. Drop it entirely, or keep
  `PFM_JWT_TOKEN` alive just for Instagram until Meta's Instagram surface (R7) exists?
  Current recommendation: keep the variable but stop depending on PFM anywhere in the hot path.
- **Q2 (LinkedIn read):** does our LinkedIn app actually hold `r_member_social`? If not, profiles
  connected with LinkedIn read `limited` and P2 skips them honestly (already handled per
  `linkedin.py:201-211`).
- **Q3 (X cost):** with `X_LIVE_ENABLED=true`, every real publish costs API credits — confirm the
  X developer tier before demoing the chat-publish flow repeatedly.

## 7. Suggested execution order & effort

P0 (30 min, mostly external portal clicks) → P1 (3-4 h) → P2 (3-4 h) → P3 (4 h) → P4 (2 h) →
P5 (3 h) → P6 (4-6 h, after doc revalidation) → P7 (1 h).
P3 can start after P0 (it only needs the existing REST path); P4 is independent; P2 is the
prerequisite for P5.
