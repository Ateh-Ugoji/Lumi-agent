# Lumi — Agent Guide

> **Nota de rutas:** el backend FastAPI que describe este archivo (`app/`, `alembic/`, `alembic.ini`, sus 5 scripts y `tests/`) se movió a `lumi/legacy/` como referencia: no se despliega ni se mantiene (ver `legacy/README.md`). El backend actual es Django (`apps/`, `config/`, `manage.py`, `lumi_ai/`). Donde este archivo diga `app/`, `alembic/` o `tests/` sin más, léelo como `legacy/app/`, `legacy/alembic/` y `legacy/tests/`.

> This file is the working map of the codebase **and** the mandatory working process.
> Deep map generated 2026-10-12 from a full read of `lumi/` (backend, frontend, data layer, services, docs).
> If anything here conflicts with the actual code, **the code wins** — then fix this file.

## MANDATORY WORKING PROCESS (every task, by default)

Unless the user explicitly says "don't plan" for a given task:

1. **Go through the task completely first.** Read every file the task touches. Do not skim.
2. **Critique and audit the task before writing any code.** Call out:
   - what is broken / half-finished / contradicts the deep map or the specs in `.agents/`
   - risks, edge cases, and what the task will NOT solve
   - better or simpler alternatives, if any
3. **Produce a step-by-step plan** (numbered, ordered, each step independently verifiable) and show it before implementing.
4. **Then execute the plan**, verifying at each step (lint: `uv run ruff check .`, tests: `uv run pytest`, and the production smoke test when touching startup/routes).
5. **Default is ALWAYS plan-first for coding tasks.** No drive-by edits, no "just one quick change."
6. **Big/serious changes must be synced in the same task.** Anything that adds or changes a pipeline, schema/table, tool, data flow, or provider requires updating, in the same change: this file, `docs/flow-map.md`, and `docs/flow-map.html`. Stale docs are treated as bugs — the flow map is the contract.

## SECRETS RULE

- **Never write real values of environment variables into any markdown/doc/code file.** Not in this file, not in `.agents/`, not in `docs/`, not in tests.
- Real keys live **only** in `.env` locally (gitignored) and the Railway dashboard for prod.
- **App-level credentials of the social networks (Meta, LinkedIn, X, Post for Me, Google, Xpoz) live ONLY in the environment** (`.env` locally, the Railway dashboard in prod). There is no database table for them: one was built and reverted on 2026-10-27 by team decision. Do not add one without an explicit OK from the team. Per-user OAuth tokens are a different thing and stay encrypted in `connected_accounts` and `mcp_auth_accounts`. Details: `docs/CONEXIONES.md`, section "Dónde viven las credenciales de la app".
- Docs may reference env var **names** only (`DATABASE_URL`, `PFM_JWT_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `SECRET_KEY`, `XPOZ_API_KEY`).
- Do not paste tokens, JWTs, connection strings, or account credentials into chat output either — reference the var name instead.

---

> Generated 2026-10-12 by six parallel analysis agents reading every file in `lumi/` (backend, frontend, data layer, services, docs/specs).
> Source: `C:\Users\USER\Downloads\Lumi-agent-backend` (project root: `lumi/`).

## What Lumi Is (in one paragraph)

Lumi is a chat-based AI creator agent for X (Twitter), built for the neatHack hackathon (Oct 10–12 2026). A user connects an X account via Post for Me OAuth; the agent (Groq primary / OpenRouter fallback LLM behind an OpenAI-style tool-calling loop) listens for trending posts and viral niche content (Xpoz), extracts a versioned "voice profile" from the user's own posts, and rewrites/repurpose captions in that voice — with deterministic must-keep enforcement plus a Jev/TypeSafe AI semantic judge. Stack: Python 3.12 + FastAPI + SQLModel (Postgres on Railway, Alembic migrations), React 19 + Vite frontend, neatlogs tracing. The product has since drifted from its hackathon MVP docs into a single-user demo hardwired to one real account (@AtehOfficial).

## At a Glance

| Layer | Status |
|---|---|
| Agent loop | Fully wired (6-iteration cap, 10-message history fit to a 6,700-est-token request budget, nested provider×model fallback, SSE streaming variant). **Every turn is classified first** (`app/agent/turn_class.py`): rules → Jev stage 2 (default OFF) → fast/full path + per-class tool tier + `effort=low` for free-tier classes; evidence gates (claim → coverage → forced block) guard zero-tool replies; timings land on `turn_classifications` and feed `/health` |
| 20 native agent tools + dynamic `mcp__*` tools | All registered and real — the last canned/fabricated fallback (peer frameworks) was **deleted 2026-10-26** with Prompt 3; MCP connector tools (Google Drive/Docs) are discovered by the **background** refresh task (`app/background/mcp_refresh.py`) and merged into the toolset from cache when a connector is authenticated — a turn never waits on discovery |
| 23 REST routes across 9 routers | 14 documented in `.agents/api-endpoints.md` (3 `/mcp/google/*` on 2026-10-21, `POST /repurpose` on 2026-10-25); **9 still undocumented**: `POST /chat/stream`, `POST /chat/title`, `DELETE /chat/history`, `GET /profiles/{id}/analytics`, `POST /pfm/connect`, `GET /pfm/callback`, `GET /trends/matches`, `POST /trends/scan`, `GET /health` |
| 21 DB tables | Models ↔ migrations in sync (migration `cefd455456a2` added `niche_framework_reports` + `post_taggings`; `f3a7c9e2b41d` added `turn_classifications` + `chat_messages.tools_used`/`reason`; `e4f1a2b3c5d6` added `mcp_auth_accounts`; `d3c4b5a6978e` added `user_search_requests`; `b7d2e5f8a3c1` added `own_post_analysis`, `profile_snapshots`, `profile_baseline`); SQLite local vs Postgres prod divergence |
| LLM services | voice extraction, repurpose (4 platforms), peer blind tagging (`app/analysis/extract.py`) — implemented; the old one-shot frameworks summary service was deleted 2026-10-26 |
| Peer frameworks | **Baseline-relative pipeline live (Prompts 1–3 done 2026-10-26)**: `discover_and_extract_niche_frameworks` + bootstrap `_ensure_peer_frameworks` run `app/services/peer_pipeline.py` (per-account fetch → 28-day baseline → 1.5×-own-median winners → blind tagging → lift → synthesis), persisting `niche_framework_reports` + `post_taggings` and bridging into `peer_frameworks`/Chroma. The absolute-impressions path and its canned "Milestones & Shipped Tech" fallback are **deleted**. Still blocked externally: Xpoz `fields` verification + credit estimate |
| Niche extraction | Live path = hardcoded query/handle lists (`bootstrap.py:27-30`), no location data; profile-derived upgrade **staged** (schemas landed in `app/schemas/niche.py`, Prompts 1–3 pending) |
| Spike alerting | Revived: analytics/Xpoz ingest appends snapshots per the shared policy (milestones 24h/72h/7d/30d, min 6h gap when unchanged) **and** the poller now runs `backfill_profile_posts` per due profile each tick (`poller.py:36-43`, non-`demo-` `pfm_account_id` only), so metrics refresh without an inbound request. Alerting still degrades honestly to the Jev backstop when PFM is unavailable |
| Analytics | Live path NULL-safe (missing metrics are NULL, coerced `or 0` for display only); fabricated demo numbers **removed** — no-data path returns zeros + an honest summary |
| Frontend | Works via localhost:8000 hardcoded; no profile switching; several dead components |
| Docs/specs | Substantially stale vs code (tools "stubs" now implemented, 1→3 profiles, etc.) |

---

---



## Core Runtime, Config & Agent Loop

### 1. Startup, CORS, routers, health

- `app/main.py:13-24` — a single `lifespan` async contextmanager does these things in order: (1) `await seed_demo_profiles()` (`main.py:45`), (2) best-effort `ensure_collections()` + framework backfill (`main.py:47-63`, both exception-shielded), (3) creates `stop_event = asyncio.Event()` and spawns `poller_task = asyncio.create_task(run_poller(stop_event))` **and** `mcp_refresh_task = asyncio.create_task(run_mcp_refresh(stop_event))` (`main.py:65-69` — MCP `tools/list` discovery runs in the background so a turn never waits on it, PROMPT 5 item 6), (4) on shutdown sets `stop_event` and gathers both tasks (`main.py:73+`). Schema is **not** created at startup — Alembic (`uv run alembic upgrade head`) owns schema; there is no `create_all()` anywhere.
- Because seeding runs *before* the yield, a slow PFM call in `seed.py` delays first-request readiness (Railway healthcheck budget is 100s, see §10). Seeding never raises (it swallows all exceptions), so it can't wedge startup — see §4.
- Background-task resilience (fixed): `_poll_once` shields each profile's work and `run_poller` wraps every tick in `try/except` that logs and continues (`poller.py:40,45,76-77`) — the old "one transient error kills polling until redeploy" bug is gone (see §7). The lifespan still only awaits both tasks at shutdown (`main.py:24+`), so a task that did die would only surface there.
- CORS: `main.py:29-34` — `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`. No `allow_credentials`, so `*` is at least spec-legal, but it is a wide-open API (any origin can drive chat/profile/delete endpoints; there is no auth layer at all).
- Routers registered at `main.py:93-101` — nine in total: `chat`, `profiles`, `alerts`, `pfm`, `trends`, `handles` (handle-search shim), `voice` (STT), `mcp_google` (Google OAuth for MCP connectors), and `repurpose` (`POST /repurpose`, the webapp composer's recaption path, added 2026-10-25). Note the CLAUDE.md architecture blurb only mentions the first three; CLAUDE.md/docs/routers.md also don't know about `voice`, `handles`, `mcp_google`, or `repurpose`.
- `GET /health` → `{**{"status": "ok"}, **payload}` (`main.py:104-115`); used by Railway `healthcheckPath`. The payload merges `recent_turn_latency()` from `app/services/turn_metrics.py` (p50/p95 over the newest 100 `turn_classifications` rows) and **omits that block entirely** when it fails or there are no rows, so the healthcheck can never break on it.
- App title `"Lumi"` (`main.py:27`); no version, no docs disabling (FastAPI's `/docs` and `/redoc` are publicly reachable under the `*` CORS policy).

### 2. Settings (`app/config.py`)

`pydantic-settings` `BaseSettings` with `env_file=".env"`, `extra="ignore"` (`config.py:7`), cached behind `@lru_cache get_settings()` (`config.py:20-22`).

| Env var | Field | Default | Required? |
|---|---|---|---|
| `DATABASE_URL` | `database_url` | `sqlite+aiosqlite:///lumi.db` (`config.py:9`) | optional (sqlite fallback) |
| `PFM_JWT_TOKEN` | `pfm_jwt_token` | `""` (`config.py:10`) | optional, silently empty |
| `GROQ_API_KEY` | `groq_api_key` | — | **required** (`config.py:12`) |
| `OPENROUTER_API_KEY` | `openrouter_api_key` | — | **required** (`config.py:13`) |
| `OPENLUX_API_KEY` | `openlux_api_key` | `None` | optional — third provider, prepended to the chain only when set (`config.py:14`) |
| `OPENLUX_MODEL` | `openlux_model` | `qwen3.8-27b` | optional — the single model used on OpenLux (`config.py:15`) |
| `TYPESAFE_API_KEY` | `typesafe_api_key` | — | **required** (`config.py:16`) |
| `NEATLOGS_API_KEY` | `neatlogs_api_key` | — | **required** (`config.py:17`) |
| `SECRET_KEY` | `secret_key` | — | **required** (`config.py:18`) |
| `XPOZ_API_KEY` | `xpoz_api_key` | `None` (`config.py:19`) | optional |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | `google_oauth_client_id` / `google_oauth_client_secret` | `""` | optional — MCP Google connectors; empty ⇒ `/mcp/google/connect` answers an honest 503, connector contributes no tools |
| `GOOGLE_OAUTH_REDIRECT_URI` | `google_oauth_redirect_uri` | `http://localhost:8000/mcp/google/callback` | optional |
| `MCP_ENABLED` | `mcp_enabled` | `true` | optional master switch for every connector |
| `MCP_GDRIVE_ENABLED` / `MCP_GDOCS_ENABLED` | `mcp_gdrive_enabled` / `mcp_gdocs_enabled` | `true` | optional per-connector kill switches |
| `MCP_TOOLS_TTL_SECONDS` / `MCP_REFRESH_TIMEOUT_SECONDS` / `MCP_CALL_TIMEOUT_SECONDS` | — | `300` / `15` / `60` | optional (discovery cache / per-turn refresh budget / per-call budget) |

Risks / notes:

- **Required-keys crash at `Settings()` construction**, which happens lazily: first at Alembic time (`alembic/env.py:22` runs at *module import*, so `uv run alembic upgrade head` fails with a pydantic `ValidationError` if any of the 5 required vars is missing) and at app startup via `session_scope → get_engine → get_settings` (`database.py:16`). It does *not* crash at Python import time of `app.main`.
- **`secret_key` is required but never used** — grep shows zero consumers in `app/` (only `config.py:16` declares it). You must set a dummy value to boot/ migrate. Same shape of problem, opposite severity: `pfm_jwt_token` defaults to `""`, so a missing PFM token fails at request time inside `PFMClient` headers (`services/pfm.py:19`) instead of at startup.
- **sqlite-by-default vs postgres-in-prod**: `.env.example:1-2` documents `postgresql+asyncpg://...`, but the code default is local sqlite (`config.py:9`). If `DATABASE_URL` is unset in Railway, both the pre-deploy migration and the runtime will happily use an **ephemeral `lumi.db`** inside the container — data (profiles, chat history) silently disappears on redeploy. Nothing warns about this.
- `extra="ignore"` means typo'd env vars (e.g. `GROQ_APIKEY`) are ignored, degrading to a confusing runtime auth error rather than a startup failure.
- `lru_cache` means `.env` edits require a process restart (fine in prod, mildly surprising under `--reload` if `get_settings()` was already called).

### 3. Database layer (`app/database.py`)

- Module-level singletons `_engine` / `_session_factory` (`database.py:9-10`) created lazily and guarded by `if ... is None` (`database.py:13-25`). Not thread-lock safe, but FastAPI/uvicorn asyncio is single-threaded per worker, so this is fine in practice; multiple uvicorn workers each build their own engine (expected).
- Factory: `async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)` (`database.py:24`). `expire_on_commit=False` is important: rows stay usable after commit, which is what lets tools mutate + commit mid-query-loop without `MissingGreenlet/DetachedInstance` errors.
- Two entry points with **identical bodies**:
  - `get_session()` (`database.py:28-30`) — an async generator shaped for FastAPI `Depends`. **Dead code: nothing in `app/` uses it** (grep shows zero `Depends(` calls in the whole backend; every router and tool uses `session_scope`).
  - `session_scope()` (`database.py:33-37`) — `@asynccontextmanager`, documented "for use outside of FastAPI's dependency injection (tools, background jobs)" but in fact it is used *everywhere*, including routers (`routers/chat.py:89,112`, `routers/profiles.py:57,87`, etc.).
- **Neither helper commits or rolls back for you.** Every caller must `await session.commit()` explicitly (e.g. `loop.py:76`, `seed.py:57`, `listening.py:84,91`). An exception between `add()` and `commit()` relies on context-manager close to discard; there is no explicit `rollback()` anywhere — mostly harmless (close discards the transaction), but it means partial multi-step writes inside one scope can be committed piecemeal: e.g. `check_trending` commits once **per spiked post** plus once for `last_polled_at` (`tools/listening.py:84,91`), so a crash mid-loop leaves some posts alerted and others not.
- No pool sizing, `pool_pre_ping`, or `echo` config; `create_async_engine(settings.database_url, echo=False)` only (`database.py:17`). For Postgres/asyncpg defaults are acceptable at demo scale.

### 4. `app/seed.py` — what it actually does now

The function is `seed_demo_profiles()` (`seed.py:15`), called from lifespan (`main.py:16`).

1. Builds a `PFMClient()` (`seed.py:17`).
2. Tries `client.get_social_account("spc_U8xOuoxKCYpKAbzUymPCd")` (`seed.py:22`); keeps it as `user_account` only if `status == "connected"` (`seed.py:23-24`). Any exception is swallowed at `logger.debug` (`seed.py:25-26`) — so with a bad/absent `PFM_JWT_TOKEN`, `user_account` stays `None` and **nothing is seeded at all**.
3. In a `session_scope`, selects `Profile` where `handle == "AtehOfficial"` OR `pfm_account_id == "spc_U8xOuoxKCYpKAbzUymPCd"` (`seed.py:31-37`).
   - If missing **and** `user_account` is truthy → insert a `Profile` with `metadata.display_name` or fallback name `"Ateh Ugoji"` (`seed.py:40-49`).
   - If it already exists → **unconditionally overwrites** `platform`, `handle`, `name` (hardcoded `"Ateh Ugoji"`, ignoring any metadata), and `pfm_account_id` (`seed.py:50-55`). A user who renamed their display name in the DB gets clobbered on every boot.
4. `await session.commit()` (`seed.py:57`), logs `"Scoped profiles successfully. Only user accounts retained."` (`seed.py:58`).
5. Outer `except Exception` logs a warning and continues (`seed.py:59-60`); `finally` closes the PFM client (`seed.py:61-62`).

Idempotency: yes — the `handle OR pfm_account_id` lookup plus `pfm_account_id` unique constraint (migration `2fe84cc3dec6`, `initial_schema.py:33`) makes re-running a no-op-ish update. It can never create duplicates.

Divergences / dead code:

- **README and CLAUDE.md are stale**: README:43 "Seeds 3 demo profiles on startup" and README:155 "Three seeded X accounts are created on startup. One is deliberately thin on post history..." — the code now seeds **one real account** (`AtehOfficial`). CLAUDE.md's "seeded 3 demo profiles … idempotent by handle" is equally wrong.
- The docstring *claims* "Ensure only the user's connected accounts exist, **purging all third-party accounts**" (`seed.py:16`) and the log claims "Only user accounts retained" (`seed.py:58`), but **there is no delete/purge code whatsoever**. Half-finished rewrite: the promise is unimplemented.
- `USER_HANDLES = {"AtehOfficial", "atehofficial", "just_ateh"}` and `USER_PFM_IDS = {"spc_..."}` (`seed.py:11-12`) are **never referenced** — leftover from the 3-profile era; the PFM id is instead hardcoded inline 5 times (`seed.py:22,34,47,54`).
- Stray double blank lines (`seed.py:27-28,38-39`) betray a quick edit.

### 5. The agent loop (`app/agent/loop.py`)

Public entry: `run_agent_loop(profile_id, user_message, on_step=None)` (`loop.py:79-86`) — wrapped in `@neatlogs.span(kind="WORKFLOW", name="agent_loop")` and `with neatlogs.identify(session_id=str(profile_id), end_user_id=str(profile_id))` so one chat request = one trace with the profile as session identity (`loop.py:85-86`). It just delegates to `_run_agent_loop` (`loop.py:89`).

Flow of `_run_agent_loop`:

0. **Classify the turn first** (PROMPT 5 / L13 item 1, `app/agent/turn_class.py`): `_agent_turn` calls `classify_turn(user_message)` as its very first step (`loop.py:734`, timed into `classify_ms`). Rules run synchronously at zero latency — a greeting whitelist plus ~17 regex rules; all agreeing → that class, disagreeing → `other` (ambiguous), nothing matched → `other`. Only then does the optional **Jev stage 2** run, and only when `TURN_CLASS_JEV_ENABLED` is on (**default OFF**; `TURN_CLASS_JEV_TIMEOUT_MS`, thresholds `TURN_CLASS_JEV_HIGH`/`_LOW` = 0.85/0.6): a 4-question Noul schema whose argmax must clear the high threshold, or — in the 0.6–0.85 band — may only pick a `FREE_TIER_CLASSES` member (`chitchat|history_meta|memory|read_cheap`); Jev unreachable/timeout/below-low → `other`. **A classifier failure can only widen access, never narrow it.** The result drives three things: the path, the tool tier, and `effort`:
   - **Tier**: `allow = allowed_for(cls.final_class)` (`loop.py:736`) → `CLASS_ALLOWED` (`turn_class.py:67`) — `chitchat`/`history_meta` see **no** tools, `memory` sees `{free}` **plus** only `remember`/`recall_memory`, `read_cheap` → `{free}`, `live_scan` → `{free, credits, llm}`, `write` → `{free, write}`, `other` → every tier.
   - **Path**: `fast_path = cls.path == "fast" and resolution is None and not _coverage_required(user_message)` (`loop.py:779-783`) — a pending MCP write or a coverage-guarded recon ask forces the full path even for a chitchat class; `path_taken` (`loop.py:784`) records the path actually taken.
   - **Effort**: `effort = "low" if cls.final_class in _LOW_EFFORT_CLASSES else None` (`loop.py:787`, `_LOW_EFFORT_CLASSES = {CHITCHAT, HISTORY_META, MEMORY, READ_CHEAP}` at `loop.py:64`); `None` means the parameter isn't sent at all.
   The turn is written to `turn_classifications` **after** the reply (see 5g).
1. **Persist the user message first**: `_save_message(profile_id, ChatRole.USER, user_message)` (`loop.py:702`, returns the row id → `user_message_id`, the classification row's `message_id`). So a crash mid-turn still leaves the user's message on disk (matches `docs/agent.md:16`).
2. **Load history after saving** (`_load_history`, `loop.py:439`): selects the last `MAX_HISTORY_MESSAGES = 10` (`loop.py:43`) messages where `role != TOOL` (`loop.py:450`), newest-first then reversed (`loop.py:451,457`), and filters out blank content (`loop.py:462`). Consequences:
   - The just-saved user message is *inside* the window (only 9 prior turns max) — the window budget is spent partly on the current message.
   - Ordering is `order_by(created_at.desc())` (`loop.py:451`): `created_at` is a `default_factory=datetime.now(UTC)` (`models/chat.py:23`) with **no sub-second guarantee of uniqueness and no id tiebreak** — two messages written in the same instant could reorder. (`/chat/history` by contrast orders by `id`, `routers/chat.py:93` — the two orderings can disagree.)
   - Because the limit is applied *before* the blank-content filter, a run full of empty tool-calling assistant turns yields **fewer than 10 usable messages** of context.
   - TOOL messages are excluded entirely (`loop.py:450`), so across requests the model never re-sees tool results, and `tool_calls` payloads are not re-serialized (`loop.py:459-463` only emits `role`/`content`) — good, because replaying an assistant `tool_calls` message without its tool responses would 400.
3. **Build the request** — two shapes depending on the path decision above:
   - **Fast path**: one system message from `build_fast_prompt(profile_id, handle, name)` (`loop.py:795`) — the persona/voice sections of `SYSTEM_PROMPT` with the operating rules **and memory block stripped** (`_FAST_PROMPT = SYSTEM_PROMPT.split("## Operating rules", 1)[0].rstrip()`, `prompts.py:138`, ~2k tokens saved per greeting), **no tool specs at all** (`tools = []`, `loop.py:798`).
   - **Full path**: `build_system_prompt(..., memory_summary=get_profile_summary(profile_id))` plus `tool_registry.list_tool_specs(allow.costs, allow.names)` (`loop.py:812`) — the per-class tier filter. MCP discovery is **not** done here: it runs in the background (`app/background/mcp_refresh.py`), and `list_tool_specs` only reads the warm cache, so `mcp_ms` is `0.0` on both paths and a cold cache simply means the connector's tools are absent this turn (prompt rule 16).
   - Then, in order: the pending-write resolution note if there was one (`loop.py:814`), the **TOOLS USED note** (rule 22 — `_build_tools_note(history)`, `loop.py:575`: newest-first, ≤5 lines of ≤8 tool names, built from the `tools_used` column of prior ASSISTANT rows; injected as its own system message *before* the history so `history_start`/`user_idx` math is unchanged), and finally `messages.pop("tools_used")` on every history dict (`loop.py:821-822`) so the key never rides the payload. Boundaries `history_start`/`user_idx` are computed from the assembled list (`loop.py:834-835`).
3b. **Request-size budget** (added 2026-10-21, `tests/test_context_budget.py`): before **every** completion — each loop iteration, because tool results grow the transcript mid-turn — `_fit_messages(messages, history_start, user_idx, tools_tokens)` (`loop.py:268-356`, wired at `loop.py:637-641`) trims the assembled request to `MAX_REQUEST_TOKENS = 6_700` estimated whole-request tokens (chars ÷ `EST_CHARS_PER_TOKEN = 3.5`, tool specs included; per-call message budget = `MAX_REQUEST_TOKENS − tools_tokens`, floor 500, `loop.py:296`). Motivation: fixed overhead is ~5,700 est tokens (system ~2,791 + tool specs ~2,907) and qwen's measured Groq input wall is ~7,000 — a loaded turn 413'd (`Requested 7154 tokens`) and the whole request died. Trim ladder, each rung only while still over budget: (1) drop the oldest old-history message; (2) shrink tool contents in every tool group **but the newest** to `OLD_TOOL_CONTEXT_CHAR_LIMIT = 1_200`; (3) drop the oldest **whole** tool group (assistant `tool_calls` + its tool responses together — history rows never carry `tool_calls`, so any assistant message with them is from this turn and whole-group deletion can never orphan a `tool_call`; the newest group is never dropped). Never dropped: system prompt(s)/resolution note, the current user message (`user_idx`), the newest tool group. Trims are in-memory only — full text stays in the DB `TOOL` rows. On any drop it logs `context budget: dropped %d oldest history message(s) and %d old tool group(s) to fit`; if still over after the ladder it logs `context over budget after trimming (...)` and sends as-is (the second Groq model's ~8,000-token wall is the backstop; a single user paste > ~8k est tokens still exceeds every wall → honest `all LLM providers failed`). Companion change: per-tool-result context cap lowered 6000 → `TOOL_CONTEXT_CHAR_LIMIT = 4000` chars (`loop.py:46`; `context_text` = `_slim_for_context` + hard truncate at `loop.py:772-775`; `sample_posts` still reach SSE). Smoke-verified 2026-10-21: 9 fat canary rows → `context budget: dropped 8 oldest history message(s) and 0 old tool group(s) to fit`, no 413, turn completed.
4. **Loop up to `MAX_TOOL_ITERATIONS = 6`** (`loop.py:625`; constant `loop.py:21`):
   - Jev sufficiency early-exit (`loop.py:626-636`): ≥ `SUFFICIENCY_MIN_TOOLS = 2` tool calls this turn and `_enough_information()` (`loop.py:361`) judges the transcript sufficient → `force_final = True`, which empties `use_tools` (`loop.py:637`) so the final completion carries no tool specs (and `tools_tokens = 0`, maximizing the message budget).
   - Fit then call: `_fit_messages(...)` → `chat_completion_with_fallback(messages, use_tools, effort=effort)` (`loop.py:948-950`; `effort` is keyword-only and reaches the provider as `reasoning_effort`).
   - **No tool calls** → claim gate may nudge/disclaim first, then the coverage evidence gate may force a coverage block (§5b/5e/5f), then a `finish_reason == "length"` reply gets one continuation call or an honest cut-off notice (§5f), then save the assistant reply (`choice.content or ""`) **with `tools_used=(tool_calls_made or None)`** (`loop.py:1027-1032` — the field lives on the FINAL reply row only, because that is the row the next turn's TOOLS USED note is read from; the mid-loop tool-calling row stays bare) and return `AgentResult`. Empty content is saved as an empty row rather than rejected.
   - **Tool calls** → append the assistant message (with live `tool_calls` objects) to the in-memory transcript (`loop.py:675`), serialize the tool calls, and persist the assistant row via `_save_message(..., content=choice.content or "", tool_calls=serialized)` (`loop.py:681-683`).
   - For each call: `_parse_tool_arguments(raw)` (`loop.py:686`, def `loop.py:468`) returns `(arguments, error)` instead of raising — malformed JSON logs a warning and feeds an honest error message back to the model (§11 item 6), never a 500.
   - `on_step({"type":"tool_start", tool, arguments})` (`loop.py:690-698`) wrapped in try/except so a broken SSE consumer can't kill the turn.
   - Execute: `asyncio.wait_for(tool_registry.call_tool(...), TOOL_TIMEOUT_SECONDS)` (`loop.py:710-713`; 120s, §5c) → registry raises `ValueError("unknown tool: …")` for unregistered names (`tools/registry.py:50-51`) and validates arguments before dispatch (§11 item 6); tool exceptions become honest model-facing failure text via `_tool_failure_message` (`loop.py:484`) — the turn survives.
   - `result_text = json.dumps(result)` (`loop.py:733`); append tool name to `tool_calls_made` (`loop.py:735`).
   - **sample_posts extraction** (`loop.py:738-747`): if the result is a dict, take `result.get("viral_posts") or result.get("posts")`, cap at **4**, and map `author` (`author` / `author_handle` / `authorUsername`), `text` (`caption`/`text` truncated to **120 chars**), `likes` (`likes`/`likeCount`), `url` (`url`/`platform_url`), `avatar_url` (author picture from the handle DB; blank → the UI falls back to unavatar). This is display-only metadata for the SSE stream; the LLM still gets the full `result_text`. (`get_analytics` additionally ships its raw `result` in `tool_executions` for the UI chart, `loop.py:754-757`.)
   - `on_step({"type":"tool_done", tool, sample_posts})` (`loop.py:760-768`), also exception-shielded.
   - Persist the tool result as a `TOOL` row (`loop.py:771`) and append `{"role":"tool","tool_call_id":id,"content":context_text}` to the in-memory transcript (`loop.py:775`, `context_text` = `_slim_for_context` result truncated to `TOOL_CONTEXT_CHAR_LIMIT`, `loop.py:772-774`) — in-memory only, so TOOL rows never re-enter context next request.
5. **Exhausted loop** → save canned `"I ran into trouble completing that — could you try rephrasing?"` as ASSISTANT (`loop.py:778-779`) and return with whatever `tool_calls_made`/`tool_executions` accumulated.
5b. **Action-claim gate** (added 2026-10-20, refined 2026-10-21, `tests/test_agent_claim_gate.py`): a zero-tool final reply is gated by one shared predicate (`_should_nudge`): (1) an explicit completed/past-action claim in the reply (`_ACTION_CLAIM_RE` = `_COMPLETED_ACTION_PATTERNS` incl. "I had saved @x … went through" / "fresh numbers", plus `_PROMISE_ACTION_PATTERNS`) fires **even when the reply also contains decline wording** (observed live: a fabricated claim sandwiched inside "I can't cleanly finish this turn"); (2) otherwise an honest marker passes — `_DECLINE_RE` covers declines (can't/failed/timed out/…) **and explicit stored/standing-data labeling** (prompt rule 15's compliant framing of `get_peer_advice` results); (3) otherwise fire when the **user's message** explicitly asked for a search/scan/recon/fetch (`_ACTION_REQUEST_RE`) **or is nothing but tagged `@handles`** (`_BARE_HANDLES_RE` — the composer's @-tag flow, prompt rule 13: a bare tag IS a lookup request), **or the reply merely presents fresh data** (`_PRESENTING_RE`: "Here's what's working…") — with zero tools that is fabrication by construction. A firing predicate injects ONE corrective nudge (`_NO_TOOL_NUDGE`, user-role message) and retries; if the second reply still trips the same predicate, `_HONESTY_DISCLAIMER` is appended to the reply the user sees (a fully neutral second reply — no claim, no presenting, no pending user request — passes without it). Gated off for greeting-only turns. This exists because qwen3.8-27b freewheeled through a whole conversation ("I've finished digging through @beaconsai's neighbourhood", "Running a fresh scan now") with `tool_calls = null` on every turn — verified in `chat_messages` rows 186–192, plus the 2026-10-20 23:02/23:12 live recurrences.
5c. **Per-tool timeout** (`TOOL_TIMEOUT_SECONDS = 120`): every `call_tool` runs under `asyncio.wait_for`; a hung Chroma/Xpoz/LLM call degrades to a visible `{"error": "Tool X timed out after 120s…"}` tool message instead of silently killing the turn (previously a hang meant: assistant tool-call row saved, no TOOL row, no final reply — the user just got silence).
5d. **MCP wiring** (added 2026-10-21; **discovery moved to the background 2026-10-25**, PROMPT 5 item 6): `mcp.refresh_tools()` is no longer called from the loop — a lifespan task (`app/background/mcp_refresh.py`, spawned at `main.py:69`) wakes every 30 s and calls the TTL-gated `refresh_tools()` (network only once `MCP_TOOLS_TTL_SECONDS` 300 s lapsed, 15 s budget, never raises), so a turn only ever *reads* the cache and a discovery round-trip can never add latency to a reply. Before the model speaks, if the previous turn left a pending write-confirmation (`mcp.pending_write()`), it is resolved from the user's message: a **clear yes** (no defer words — "yes, but later"/"wait" cancel) executes the tool via the normal execution path, records it in `tool_calls_made`, persists a TOOL row with the **real** result payload and `reason="user confirmed the pending write"`, and injects a system note carrying that outcome (success or honest failure) so the model can never narrate an unrun write; anything else records a cancelled note (no TOOL row, no execution entry). Resolution happens even when the model would otherwise skip tools — and a pending write forces the **full** path (`loop.py:781`).
5e. Gate regexes were extended in the same change: `\bi(?:'ve |'d | have | had | )(?:already )?…` (was `\bi ` — a space, so "I've"/"I'd" never matched the claim patterns: a pre-existing latent bug) and doc-creation claim families ("I've created the doc", "I drafted a document … went through", "made a Google Doc"), so fabricated doc work in a zero-tool reply is nudged like every other fabricated action.
5f. **Coverage evidence gate + finish_reason handling** (added 2026-10-25, `tests/test_coverage_gate.py`, prompt rules 17–20 — fixes the Beacons failure, chat_messages row 273: three tools ran, none a scan of the named handles, reply opened "I have the full picture" for an account it never looked up). When the user's message **names @-handles AND asks for a scan or a deliverable** (`_coverage_required` = `_ACTION_REQUEST_RE` or `_DELIVERABLE_RE` over handles from `_HANDLE_TAG_RE`, normalized lower/no-@/unique), the loop tracks per-handle coverage this turn from `check_niche_trends` results (`_record_scan_coverage`: `scanned (n posts)` from the result's `scanned_handles` map, `failed (why)` from `failed_handles`/whole-call errors, else `not_run`), plus `peers_discovered` and the `get_peer_advice` provenance (`niche_title`/`source_handles`/`age_days`). At the final reply, precedence: (1) the §5b claim gate nudges first (its locked tests/text unchanged); (2) else if any named handle is `not_run` and the reply is not an honest decline → ONE `_COVERAGE_NUDGE` naming the missing handles (this fires **even when other tools ran** — "some tool ran" no longer satisfies the gate); (3) on any still-incomplete coverage, the reply is forced open with the `Recon coverage: @h: status | … | frameworks used: …` block (`_coverage_block`) and the "full picture" family is stripped to "partial picture" (`_FULL_PICTURE_RE`) — unless the reply is a zero-tool honest decline (that decline IS the disclosure; locked by `test_honest_decline_gets_no_nudge_and_no_disclaimer`). Also: `finish_reason == "length"` on the final reply → exactly ONE continuation call with a "continue where you cut off" user message (`_continue_truncated`); if the continuation is again truncated (or it errors), an explicit `[cut off again…]`/`[Note: this reply was cut off…]` marker is appended and logged — a 7,163-char plan previously ended mid-sentence with the loop never noticing. `finish_reason` is read from `completion.choices[0]`, **not** `.message`.
5g. **Turn classification row + timings** (PROMPT 5 item 8, added 2026-10-25, `tests/test_prompt5_acceptance.py`): every exit path funnels through `_finish(taken, content)` (`loop.py:873`), which logs one `turn metrics:` line and then `_schedule_classification(TurnClassification(...))` (`loop.py:903-925`) — a **fire-and-forget** `asyncio.create_task` held in `_classification_tasks` so it can't be GC'd; `_write_classification` (`loop.py:556`) swallows every exception at `logger.debug`, so a failed write can never touch the reply. The row carries `message_id`/`message_text_hash`/`message_preview`, `rule_class`/`rule_matched`, the Jev block (`jev_called/…/jev_error`), `final_class`, `path_taken`, `tools_called`, `total_latency_ms`, and `timings` — `classify_ms`, `prompt_ms`, `completion_ms`, `total_ms` always, plus `mcp_ms`/`tool_ms`/`jev_ms`/`model`/`prompt_tokens`/`completion_tokens`/`reasoning_tokens` **only when measured** (an absent key is a NULL in the JSON, never `0`), and `credits_spent=None` / `user_corrected=None` because nothing meters them yet. Those rows are read back by `recent_turn_latency()` (newest 100) which `GET /health` merges into its payload (`main.py:105-115`) — the latency block is **omitted entirely** on any failure or when no turns exist, so the healthcheck can never fail on it and a missing metric is absent, not zero.

Quirks / bugs found (verified, not speculative):

- **"Assistant saved twice" — checked, NOT present.** The two `_save_message(ASSISTANT, ...)` sites in the tool path (`loop.py:667` final reply vs `loop.py:681-683` tool-calling turn) are mutually exclusive branches of `if not choice.tool_calls`. Each iteration persists exactly one assistant row. (Multiple assistant rows *per request* are normal — one per tool-calling iteration plus the final one — but that's not duplication.)
- **Empty-content assistant rows do leak into the UI history.** Tool-calling turns with no prose persist `content=""` (`loop.py:681-683`), and `/chat/history` filters only `role != TOOL`, not blank content (`routers/chat.py:92`) → the frontend can render empty assistant bubbles. The *LLM* context correctly skips them (`loop.py:462`), so DB, UI, and model context all disagree.
- **Empty/whitespace user message** is persisted (`loop.py:532`) but then filtered out of context (`loop.py:462`) — the model can receive a prompt with *no user turn at all* (system + older history only), and history may then end on an assistant message, which some OpenAI-compatible backends reject.
- Assistant messages that carry `content=None` (common for pure tool-calling turns) are stored as `""`, so on reload they're dropped from context — harmless for API validity, but it means long tool-heavy turns leave *no* textual trace in future context.
- `chat_completion_with_fallback` failures (`RuntimeError("all LLM providers failed")`, `providers.py:161`) are not caught in the loop → unhandled 500 for `POST /chat` (the stream endpoint converts it to an `error` event, `routers/chat.py:65-66`), with the user message already persisted as a dangling row. (Mitigated, not removed: §5 3b's request-fit keeps normal turns under qwen's wall and §6's Groq model chain absorbs 413/429 — but a >8k-token single message or every model failing still lands here.)
- No streaming of assistant *tokens* — `on_step` only emits `tool_start`/`tool_done`; the final text arrives only via the `done` event the router synthesizes (`routers/chat.py:64`).
- `AgentResult` (`loop.py:37-41`) carries `tool_calls_made: list[str]` and `tool_executions: list[dict]`; `tool_executions` entries are `{name, arguments, sample_posts}` (`loop.py:749-753`, plus the raw `result` dict for `get_analytics`, `loop.py:754-757`) — for everything else the client gets samples, not the raw tool output.
- System prompt (`prompts.py`) hardcodes the `@AtehOfficial` handle in rule 2 (`prompts.py:8`) and a fixed niche-trends handle list (`prompts.py:14`) — prompt is a static module constant, no templating/versioning (`docs/agent.md:40` acknowledges this). Rules 13–15 (fabrication fix) and rule 16 (MCP connectors: plain-language routing, the write-confirmation protocol, "say Google isn't connected" when no `mcp__*` tools are present) were appended 2026-10-20/21; **rules 17–20** were appended 2026-10-25 (17: coverage line per named handle, "full picture" only when every named handle was scanned; 18: stored frameworks used as evidence only when the account is in `source_handles`; 19: no invented numbers/locations/dates — placeholder or ask, and use today's date; 20: state whose account the deliverable is for when ambiguous). `build_system_prompt` also injects `- today's date: <weekday, DD Month YYYY> (UTC)` into the profile-context block (rule 19 depends on it) — the only templating in an otherwise static prompt.

### 6. Providers (`app/agent/providers.py`)

- Constants: `GROQ_BASE_URL = "https://api.groq.com/openai/v1"` (`providers.py:13`), **`GROQ_MODEL = "qwen/qwen3.8-27b"`** (`providers.py:14` — still an odd/possibly-future model slug; re-verify against Groq's catalog when touching the chain), `OPENROUTER_BASE_URL` + `OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"` (`providers.py:16-17`), `OPENLUX_BASE_URL = "https://api.openlux.ai/v1"` (`providers.py:19`), `TIER_MODELS = {"small": "openai/gpt-oss-20b", "large": "openai/gpt-oss-120b"}` (`providers.py:22` — same IDs on Groq and OpenRouter, so a tier override applies to whichever provider answers), **`GROQ_FALLBACK_MODEL = TIER_MODELS["large"]`** (`providers.py:30`), neatlogs endpoint `https://ingest.neatlogs.com`, workflow name `"lumi"` (`providers.py:32-33`).
- `ProviderConfig` dataclass = `{name, client, models: list[str]}` (`providers.py:36-42`) — `models` is the ordered chain tried on that provider; an explicit `model=` argument overrides it with a single pinned candidate (repurpose tiering: "small" must never be silently upgraded).
- **Lazy singleton** `_providers` (`providers.py:45`) built on first call of `get_providers()` (`providers.py:75-110`): calls `_init_tracing(settings)` → `neatlogs.init(...)` (`providers.py:66-72`, invoked at `providers.py:79`, comment "must init before wrap()"), then appends **OpenLux only when `OPENLUX_API_KEY` is set** (`models=[settings.openlux_model]`, default `qwen3.8-27b` — `config.py:14-15`) plus the fixed **Groq** (`models=[GROQ_MODEL, GROQ_FALLBACK_MODEL]`) and **OpenRouter** (`models=[OPENROUTER_MODEL]`) entries, each `AsyncOpenAI` wrapped once with `neatlogs.wrap(..., provider="openlux"/"groq"/"openrouter")` (`providers.py:82-109`). Clients are never rebuilt per request (matches `docs/agent.md:30`).
- **Groq carries a two-model chain** (`providers.py:24-30,99`): `qwen/qwen3.8-27b` first (primary; measured ~7,000-input-token request wall — 413 above it), then `openai/gpt-oss-120b` (~8,000 wall, tool-calling verified) — so a qwen 413 (request-too-large) or 429 (daily-token) from a tool-heavy turn is answered on the second Groq model instead of burning the OpenRouter leg (which is 402-limited by an empty credit balance). Verified live 2026-10-21: pre-fix a 7,154-token request 413'd on qwen and the whole turn died; post-fix §5 3b's request-fit keeps the typical turn under qwen's wall and this chain covers the remainder.
- **Nested retry** — `chat_completion_with_provider(messages, tools, model=None)` (`providers.py:113-161`): outer loop over providers in list order (OpenLux → Groq → OpenRouter), inner loop over `candidates = [model] if model else provider.models` (`providers.py:129-131`); each attempt calls `client.chat.completions.create(model=candidate, messages=..., tools=tools or None)` (`providers.py:133-137`), returns `(completion, provider_name)` on first success, and logs `provider X answered with fallback model Y` when a non-first candidate answers (`providers.py:138-141`). **Only `openai.APIError` triggers the next candidate** (`providers.py:143`); anything else (e.g. a `pydantic`/`ValidationError` from a malformed response, a `TypeError`) escapes immediately. Each failure logs `provider X model Y failed, trying next model|next provider` plus a structured `neatlogs.log(...)` carrying the model name (`providers.py:145-157`) and sets `last_error`. All candidates exhausted → `RuntimeError("all LLM providers failed") from last_error` (`providers.py:161`), which masks the original status/message in the HTTP response (only visible chained in logs). In the openai SDK `APIError` is the broad base (`APIStatusError`/4xx/5xx, `APIConnectionError`, timeouts), so auth, rate-limit, and *bad-request* errors all fall through the chain.
- `chat_completion_with_fallback(messages, tools)` (`providers.py:164-168`) is the provider-name-dropping wrapper the loop (and title generation) uses.
- No `temperature`, `max_tokens`, or `tool_choice` are ever set; the only env model override is `OPENLUX_MODEL`.
- `get_audio_provider()` (`providers.py:50-63`) is the one other `AsyncOpenAI` constructor — a plain, unwrapped Groq client for `POST /voice/transcribe` STT, deliberately outside the chat chain (documented exception to the "only `get_providers()`" rule, `docs/agent.md:36`). Note tracing init is **lazy, not in lifespan** — `neatlogs.init` first runs on the first chat/title request, so tracing misconfig surfaces mid-traffic, and `/health` never exercises it.

### 7. Background poller (`app/background/poller.py`)

- `TICK_SECONDS = 120` (`poller.py:13`) with an in-code hint "drop to 30 for demos — see docs/background.md"; `DECAY_INTERVAL_DAYS = 7` gates the memory sweep.
- `_poll_once()` (`poller.py:23-52`): loads all `PollConfig` rows with `is_active == True` in a short-lived scope, closes it, computes `now = datetime.now(UTC)` and filters to **due** configs (`last_polled_at is None or (now - last_polled_at) >= interval_minutes * 60`), then per due config runs two separately-shielded steps: (1) `backfill_profile_posts(session, config.profile_id, profile.pfm_account_id)` for every profile whose `pfm_account_id` is set and not `demo-*` (metrics refresh, `poller.py:36-43`), (2) `check_trending(config.profile_id)`. Each is wrapped in its own `try/except` that logs and continues (`poller.py:40,45`), so a PFM/Xpoz failure neither skips the spike check nor affects the other profiles. Default `interval_minutes = 5`, `is_active = False` (`models/poll.py:11-12`), one config per profile (`unique=True`, `models/poll.py:10`).
- **Exception handling — fixed** (this was the old silent-death bug: one transient error killed polling until redeploy, surfaced only at shutdown `main.py:24`). `_poll_once` now shields per-profile work and `run_poller` wraps every tick (`poller.py:76-77`, `Poller tick failed, will retry`). Still missing: backoff/alerting — failures are logged and retried on the next tick with no jitter or visibility.
- `_decay_pass()` (`poller.py:55-70`) runs after every tick but only sweeps once per `DECAY_INTERVAL_DAYS = 7` (module-level `_last_decay`); it lazily imports `app.services.memory` and deletes entries untouched for `MEMORY_DECAY_DAYS = 90`. Shielded separately (`poller.py:68`), so a Chroma failure never aborts the tick.
- **Bootstrap-on-every-tick was deliberately removed**: `bootstrap_profile` (voice extraction + peer-framework scan) can hang long enough to fail the Railway healthcheck and crash-loop the service; it now runs on demand only, fired once per profile from the PFM OAuth callback (`schedule_profile_bootstrap`).
- `run_poller(stop_event)` (`poller.py:72-80`): `while not stop_event.is_set(): await _poll_once(); await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)` catching `TimeoutError` to tick again — clean shutdown that wakes instantly when the lifespan sets the event (`main.py:65+`).
- Throttling correctness depends on `check_trending` writing `config.last_polled_at` (`tools/listening.py:87-91`) — it only does so if a `PollConfig` row still exists for that profile (it re-queries rather than reusing the one from `_poll_once`). If `check_trending` raises before that write, the profile is re-attempted every tick.
- **Timezone caveat**: `now` is tz-aware UTC (`poller.py:17`) and is subtracted from `last_polled_at`. On Postgres/asyncpg the column round-trips tz-aware, but on the default SQLite path a naive `datetime` read back from the DB raises `TypeError: can't subtract offset-naive and offset-aware datetimes` → poller death (see the bug pattern above). Also note `last_polled_at` is updated even when *nothing* was alerted, which is correct.
- Only the profile's *tracked posts* are spike-checked; the poller itself never fetches new metrics — snapshots accumulate via the shared ingest policy when `get_analytics`, `backfill_posts`, or `extract_voice_profile` runs (see §3 and the Profile-Extract section).

### 8. Migrations (Alembic)

- `alembic.ini` is the stock template: `script_location = %(here)s/alembic` (`alembic.ini:8`), `prepend_sys_path = .` (`alembic.ini:21`), `path_separator = os` (`alembic.ini:74`), placeholder `sqlalchemy.url = driver://user:pass@localhost/dbname` (`alembic.ini:89`) that is **overridden in code**. Ruff/black `post_write_hooks` are present but commented out (`alembic.ini:92-113`) — consistent with `pyproject.toml` excluding `alembic/versions` from ruff entirely.
- `alembic/env.py`:
  - `import app.models  # noqa: F401` (`env.py:9`) — imports the model package for the side effect of registering every table on `SQLModel.metadata`; without it autogenerate sees an empty metadata.
  - `config.set_main_option("sqlalchemy.url", get_settings().database_url)` (`env.py:22`) — env vars required even to run migrations (§2).
  - `target_metadata = SQLModel.metadata` (`env.py:24`); autogenerate comparison is default (no `compare_type`/`compare_server_default` tweaks — type comparison drift is therefore possible).
  - Async online mode: `async_engine_from_config(..., prefix="sqlalchemy.", poolclass=pool.NullPool)` (`env.py:69-73`), `connection.run_sync(do_run_migrations)` (`env.py:76`), `asyncio.run(...)` (`env.py:84`) — note this means **alembic can't run inside an already-running event loop** (fine for CLI).
  - Offline mode supported with `literal_binds=True` (`env.py:44-50`).
- **`script.py.mako` forces `import sqlmodel`** (line 12) — this is the documented SQLModel autogenerate gotcha (CLAUDE.md): generated revisions render `sqlmodel.sql.sqltypes.AutoString()/UTCDateTime()` without importing the package. The ten autogenerated revisions carry the import (`initial_schema.py:12`, `46283ff46bfd:12`, `7c3e1a9b4d2f`, `8c4f1a9d2e7b`, `b7d2e5f8a3c1:28`, `d3c4b5a6978e`, `e4f1a2b3c5d6`, `f3a7c9e2b41d`, `2f30380b96df`, `cefd455456a2`); the hand-written eleventh, `b7f3a91c5d20`, adds a plain `sa.String()` column so it needs no sqlmodel import.
- **Revision `2fe84cc3dec6` — "initial schema"** (`versions/2fe84cc3dec6_initial_schema.py`, base, `down_revision=None`), creates 10 tables:
  - `profiles` (`:25-34`) — unique `pfm_account_id`; **no index on `handle`** even though seed and probably routers query by handle.
  - `chat_messages` (`:35-46`) — `role` as native enum `chatrole(USER/ASSISTANT/TOOL)`, `tool_calls` JSON nullable, index on `profile_id`.
  - `poll_config` (`:47-56`) — **unique** index on `profile_id` (one config per profile), nullable `last_polled_at`.
  - `posts` (`:57-69`) — unique `(profile_id, platform_post_id)` named `uq_posts_profile_id_platform_post_id`, nullable `alerted_at`, `alert_dismissed` bool, index on `profile_id`.
  - `repurpose_requests` (`:70-79`), `style_answers` (`:80-89`), `voice_profiles` (`:90-103`), `metric_snapshots` (`:104-117`), `repurpose_attempts` (`:118-134`), `user_actions` (`:135-144`, enum `useractiontype(ACCEPT/EDIT/REJECT)`).
  - Notables: `voice_profiles` has `uq(profile_id, version)` (`:100`) **plus** the partial unique index `uq_voice_profiles_current_per_profile` with `postgresql_where=sa.text('is_current = true')` (`:103`), and `metric_snapshots` has both `uq(post_id, captured_at)` (`:114`) and a hand-written descending composite index `ix_..._captured_at DESC` via `sa.literal_column('captured_at DESC')` (`:117`).
  - **Portability bug — fixed 2026-10-26**: `postgresql_where` is a *dialect-scoped* kwarg, so on the default SQLite dev DB this index used to degenerate to a **plain UNIQUE index on `profile_id`** (one voice-profile row per profile), breaking the versioned-voice-profile design locally. `app/models/voice.py` now also declares `sqlite_where=text("is_current = 1")`, and revision `2f30380b96df` rebuilds the index where it was still degenerate. Postgres was always fine (no-op migration there).
  - Downgrade (`:148-172`) mirrors in reverse order.
- **Revision `46283ff46bfd` — "add listening_matches table"** (`versions/46283ff46bfd_add_listening_matches_table.py`, `down_revision='2fe84cc3dec6'`): creates `listening_matches` (`:25-40`) with `profile_id` FK → profiles, `platform`, `platform_post_id`, `author_handle`, `caption`, `platform_url` (all NOT NULL), `metrics` JSON nullable, `discovered_at` NOT NULL, nullable `alerted_at`, `alert_dismissed` bool, unique `(profile_id, platform_post_id)` (`:39`), plus index on `profile_id` (`:41`). Per CLAUDE.md this is a scaffold — nothing writes to it yet. Downgrade drops index then table (`:45-49`).
- **Revision `7c3e1a9b4d2f` — "add peer_frameworks table"** (`versions/7c3e1a9b4d2f_*.py`, `down_revision='46283ff46bfd'`): creates `peer_frameworks` (id PK, profile_id FK indexed, `query`/`niche_title` VARCHAR default "", `payload` JSON, `analyzed_peers_count` int default 0, `created_at`).
- **Revision `8c4f1a9d2e7b` — "add user_activity table"** (`down_revision='7c3e1a9b4d2f'`): creates `user_activity` (unique `(profile_id, platform_post_id)`, NOT NULL `kind` string, index on `profile_id`).
- **Revision `b7d2e5f8a3c1` — "profile-extract fixes"** (`versions/b7d2e5f8a3c1_profile_extract_fixes.py`, `down_revision='8c4f1a9d2e7b'`, carries `import sqlmodel` at `:28`): creates `own_post_analysis`, `profile_snapshots`, `profile_baseline`; adds nullable columns to `posts` (`source`, `last_seen_at`, `is_deleted_suspect`/`text_truncated` NOT NULL with `server_default=false`, `kind`, `kind_source`, `conversation_id`, `thread_position`, `is_thread_head` — `:78-88`), `profiles` (`timezone`, `timezone_source` — `:91+`), `metric_snapshots` (`age_hours`, `source`), and `user_activity` (`likes`/`replies`/`views`, `source`). Flips the four `metric_snapshots` metric columns from NOT NULL to nullable (SQLite via `batch_alter_table`). Runs two **one-way** data fixes documented in the file header: Rule A (`views==0` with any other metric >0 → all four NULL; 0 rows) and Rule B (all four ==0 AND snapshot >72h after publish → all four NULL; 24 rows on the real DB, all profile 16 — payload loss, not performance). Downgrade is **partially destructive by design**: NULL metrics coerce back to 0 (documented in the header), booleans/strings drop. Copy-tested up then down against a copy of real data, then applied to the shipped `lumi.db`.
- **Revision `d3c4b5a6978e` — "add user_search_requests table"** (`versions/d3c4b5a6978e_add_user_search_requests.py`, `down_revision='b7d2e5f8a3c1'`): creates `user_search_requests` (id PK, `profile_id` FK→profiles NOT NULL + index, `handle` VARCHAR NOT NULL normalized lowercase-no-@, `request_note` VARCHAR nullable, `created_at` UTCDateTime NOT NULL). Append-only user-request log; applied to the shipped `lumi.db`.
- **Revision `e4f1a2b3c5d6` — "add mcp_auth_accounts table"** (`versions/e4f1a2b3c5d6_add_mcp_auth_accounts.py`, `down_revision='d3c4b5a6978e'`): creates `mcp_auth_accounts` (id PK, `account` VARCHAR NOT NULL **unique** — one row per auth account, e.g. `"google"` shared by both Google connectors, `access_token` VARCHAR NOT NULL, `refresh_token` VARCHAR nullable, `expires_at` UTCDateTime nullable, `scopes` JSON nullable, `updated_at` UTCDateTime NOT NULL). OAuth token store for MCP connectors (`app/services/mcp.py:store_tokens`); applied to the shipped `lumi.db`. Tokens live only here — never in code, docs, or env files.
- **Revision `f3a7c9e2b41d` — "add turn_classifications"** (`versions/f3a7c9e2b41d_add_turn_classifications.py`, `down_revision='e4f1a2b3c5d6'`): creates `turn_classifications` (one row per turn, written fire-and-forget after the reply — see §5 5g) and adds `chat_messages.tools_used`/`reason`. Read by `app/services/turn_metrics.recent_turn_latency()`, which `GET /health` merges in.
- **Revision `2f30380b96df` — "fix sqlite partial voice index"** (`versions/2f30380b96df_fix_sqlite_partial_voice_index.py`, `down_revision='f3a7c9e2b41d'`): on **SQLite only** drops and recreates `uq_voice_profiles_current_per_profile` with `sqlite_where=sa.text("is_current = 1")`, so existing dev databases stop carrying the degenerate plain UNIQUE index; a no-op on PostgreSQL. **Downgrade is deliberately a no-op (one-way fix)** — the old state cannot be recreated once a profile has several voice-profile versions (`CREATE UNIQUE INDEX` without WHERE raises IntegrityError there, verified). Regression tests: `tests/test_voice_index_sqlite.py` (3) migrate a fresh SQLite DB and assert the index is partial, that a second version can be inserted after the flip, and that a second *current* row is still rejected.
- Migration workflow risk called out in CLAUDE.md remains real: read every autogenerated file (renames show as drop+add; partial indexes need manual review).

### 9. `pyproject.toml`

Runtime deps (`pyproject.toml:9-24`), all lower-bound pins:

```
aiosqlite>=0.22.1        alembic>=1.20.0        asyncpg>=0.32.0
fastapi>=0.143.0         greenlet>=3.5.6        httpx>=0.28.1
mcp==2.3.0 (pinned)      neatlogs>=1.4.26       openai>=3.28.0
psycopg2-binary>=2.9.13  pydantic>=2.14.0       pydantic-settings>=2.15.0
sqlmodel>=0.0.48         typesafe-sdk>=0.7.4    uvicorn[standard]>=0.54.0
```

- Both **`asyncpg`** (async Postgres, used by the runtime engine and alembic) **and `psycopg2-binary`** (sync) are pinned — psycopg2 appears unused (alembic uses the async engine); `greenlet` is a SQLAlchemy-async requirement made explicit. `typesafe-sdk` (not `typesafe-ai`) per CLAUDE.md. **No LLM SDK other than `openai`** — Groq/OpenRouter ride the OpenAI-compatible client.
- **`mcp==2.3.0` is the only exact pin in the file** (deliberate — the SDK's public surface moved between 1.x and 2.x: `streamable_http_client`, snake_case `Tool.input_schema`, `.is_error`/`.structured_content`; don't "upgrade it" casually, and don't code to 1.x memory). It pulls `httpx` 2.x transitively under the alias `httpx2` — the app's own `httpx` 0.28 stays untouched.
- `requires-python = ">=3.12"` (`pyproject.toml:8`) matching `.python-version` = `3.12`.
- `[tool.uv] package = false` (`pyproject.toml:26-27`) — the project is not built/installed as a package; `uv run` executes from source.
- `[tool.ruff] extend-exclude = ["alembic/versions"]` (`pyproject.toml:29-30`) — **there is no `[tool.ruff.lint] select`**, so only ruff's default rules run (E4/E7/E9 + F). Notably `# noqa: BLE001` comments used across `seed.py:25,59`, `loop.py:136,170`, `routers/chat.py:65,148` refer to a rule that is **not enabled** — they are no-ops today (either the config is half-finished or the comments are cargo-cult).
- Pytest (`pyproject.toml:32-34`): `asyncio_mode = "auto"` (pytest-asyncio auto-discovers `async def` tests) and `pythonpath = ["."]` (so `tests/` can `import app.*` without install).
- Dev dependency group (`pyproject.toml:36-41`): `pytest>=9.1.1`, `pytest-asyncio>=1.4.0`, `ruff>=0.17.0`. No mypy/pyright — **no type-checking step exists** despite the codebase being typed.

### 10. Deployment (`railway.json`, `.env.example`)

```json
{ "build": { "builder": "RAILPACK" },
  "deploy": { "preDeployCommand": ["uv run alembic upgrade head"],
    "startCommand": "uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health", "healthcheckTimeout": 100,
    "restartPolicyType": "ON_FAILURE" } }
```
(`railway.json:1-13`)

- Builder `RAILPACK`; migrations run as a **preDeploy** command, so a failing migration (including the required-env-vars crash from §2) aborts the deploy before the new container starts — good — but it also means **old and new schema must be backward-compatible with the still-running previous version** during the window (no such discipline is documented).
- Start command binds `0.0.0.0:$PORT`; `/health` gates readiness with a 100s timeout — comfortably above the seed's PFM roundtrip unless PFM hangs (the seed has **no timeout of its own**; it awaits `client.get_social_account` before yielding, `main.py:16`).
- `restartPolicyType: ON_FAILURE` — note the *poller task* failing does **not** fail the process, so `ON_FAILURE` never rescues a dead poller (§7).
- `.env.example` mirrors §2: `DATABASE_URL`, `PFM_JWT_TOKEN`, `XPOZ_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `SECRET_KEY` — all shown blank, with no indication of which are required; `DATABASE_URL` comment says Postgres+asyncpg while the code silently defaults to sqlite (§2's ephemeral-DB trap). Railway env vars are set in the dashboard (CLAUDE.md), not committed.
- Postgres is a separate Railway service in the same project; nothing in `railway.json` wires it (no `dependsOn`/reference), so `DATABASE_URL` must be linked manually.

### 11. Bug / inconsistency roundup (this slice)

1. **Docs vs code**: README:43/155 + CLAUDE.md claim "3 demo profiles" seeded; `seed.py` now hardcodes one real account (`AtehOfficial`) — README:43, README:155, `seed.py:40-55`.
2. **`seed.py` docstring/log promise purging third-party profiles; no purge exists** (`seed.py:16`, `seed.py:58`), and `USER_HANDLES`/`USER_PFM_IDS` are dead constants (`seed.py:11-12`).
3. **`SECRET_KEY` is required but unused** (`config.py:16`); conversely missing other keys only explode at alembic/startup time via `env.py:22`.
4. **`get_session()` is dead code** — no `Depends(` anywhere; everything uses `session_scope` (`database.py:28-30`).
5. **Poller error handling (fixed) + timezone risk (open)**: per-profile work and every tick are now wrapped in `try/except` that logs and continues (`poller.py:40,45,76-77`), so no single failure kills polling for the process lifetime. Still open: the naive/aware datetime subtraction risk on the SQLite default (`poller.py:28-33`) — a naive `last_polled_at` read back from SQLite raises `TypeError` inside the due-filter, and there is still no backoff/alerting on repeated failures.
6. **Tool errors and malformed tool arguments** — **fixed** (`app/agent/loop.py`, `app/tools/registry.py`, `tests/test_agent_tool_errors.py`). `_parse_tool_arguments` returns `(dict, error)` instead of raising; `_tool_failure_message` converts `ValueError` to model-facing text and all other exceptions to a generic "do not pretend it worked — retry once or tell the user which capability is unavailable" message; both flow through the existing `result_text`/tool-message path. `registry.call_tool` now validates arguments before dispatch: undeclared keys are dropped with a warning; missing required keys raise a `ValueError` listing the missing names and the declared parameters. Tests cover the raising tool, the malformed-JSON tool, the missing-required-argument tool, and the extra-key tool — none abort the turn.
7. **Empty assistant rows pollute `/chat/history`** (saved at `loop.py:681-683`, not filtered at `routers/chat.py:92`) though the model context filters them (`loop.py:462`).
8. **Fabricated action claims + silently dead recon turns — fixed** (2026-10-20). Verified in `chat_messages` rows 186–192: qwen3.8-27b replied "Running a fresh scan now", "Got it. I'll do a fresh peer recon", "I've finished digging through @beaconsai's neighbourhood… I ran a fresh recon" — every one with `tool_calls = null` (zero tools). Two earlier genuine recon turns (rows 174, 184) called tools but **hung mid-flight** (no per-tool deadline; external call never returned → no TOOL row, no final reply, user got silence). Fixes: the action-claim gate + per-tool 120s timeout in `app/agent/loop.py` (§5 5b/5c, `tests/test_agent_claim_gate.py`); pasted handles are now recorded as user requests via `save_user_request` (§3) instead of being fair game for the profile-scoped peer stores, with prompt rule 13 forcing `save_user_request` → `check_niche_trends` ordering, in-turn action (rule 14), and honest labeling of `get_peer_advice` (rule 15).
9. **Model IDs are hardcoded constants** — Groq `[qwen/qwen3.8-27b, openai/gpt-oss-120b]` (primary + fallback, `providers.py:14,30`), OpenRouter `meta-llama/llama-3.3-70b-instruct`, repurpose tiers via `TIER_MODELS` (`providers.py:22`); only OpenLux is env-overridable (`OPENLUX_MODEL`). `GROQ_MODEL = "qwen/qwen3.8-27b"` still deserves a catalog sanity check.
10. **Partial unique index is Postgres-only** (`initial_schema.py:103`) — on the default SQLite dev DB voice-profile versioning silently breaks.
11. **Ruff lint config is default-only**, making the widespread `# noqa: BLE001` annotations inert (`pyproject.toml:29-30`).
12. History ordering by `created_at` vs `/chat/history` ordering by `id` can disagree under same-timestamp writes (`loop.py:451` vs `routers/chat.py:93`).
13. No `select()`-level pagination/pool tuning and no rollback helpers — commit discipline is entirely per-caller (`database.py:33-37`).
---

## Data Model & Schema

Stack: SQLModel (SQLAlchemy 2.0) over PostgreSQL in prod (Railway), **SQLite locally** (`.env:2` → `DATABASE_URL=sqlite+aiosqlite:///lumi.db`; confirmed against the shipped `lumi.db`). Schema is Alembic-managed; eleven revisions: `2fe84cc3dec6` (initial, 10 tables), `46283ff46bfd` (adds `listening_matches`), `7c3e1a9b4d2f` (adds `peer_frameworks`), `8c4f1a9d2e7b` (adds `user_activity`), `b7d2e5f8a3c1` (profile-extract fixes: adds `own_post_analysis`, `profile_snapshots`, `profile_baseline`; additive columns on `posts`/`metric_snapshots`/`profiles`/`user_activity`; one-way NULL-metric data fixes), `d3c4b5a6978e` (adds `user_search_requests`), `e4f1a2b3c5d6` (adds `mcp_auth_accounts`), `f3a7c9e2b41d` (adds `turn_classifications` + nullable `chat_messages.tools_used`/`reason`), `2f30380b96df` (rebuilds the SQLite voice-profile partial unique index, one-way downgrade) and `cefd455456a2` (adds `niche_framework_reports` + `post_taggings`, peer-pipeline Prompt 2), `b7f3a91c5d20` (adds `listening_matches.author_avatar_url`, ChronicOnline picture sync). There is no `create_all()` in app code (`alembic/env.py` wires `SQLModel.metadata` via `import app.models`; `alembic.ini`'s `sqlalchemy.url` placeholder is overridden at runtime from settings). Models and migrations are in sync column-for-column — the drift in this repo is **spec-doc vs reality**, not model vs migration.

### Table: `profiles` (`app/models/profile.py:6-20`, migration `2fe84cc3dec6:25-34`, `b7d2e5f8a3c1`)

| Column | Model type | DB type | Constraints / notes |
|---|---|---|---|
| `id` | `int \| None` | INTEGER | PK (autoincrement) |
| `name` | `str` | AutoString (VARCHAR) | NOT NULL |
| `platform` | `str = "x"` | AutoString | NOT NULL; app-side default `"x"` (profile.py:11), no server default |
| `handle` | `str` | AutoString | NOT NULL — **no unique constraint** (spec doesn't ask for one; seed dedup is app-level, seed.py:31-37) |
| `pfm_account_id` | `str` | AutoString | **UNIQUE + NOT NULL** (model: `Field(unique=True)` profile.py:13; migration:33) — a profile cannot exist before the PFM OAuth callback |
| `created_at` | `datetime` | `UTCDateTime` | NOT NULL; Python default only (`datetime.now(UTC)` profile.py:14), no `server_default` |
| `timezone` | `str \| None` | AutoString | NULLable; IANA name when `user_confirmed`, else weak-inferred offset like `"UTC+01:00"` (see Profile-Extract section) |
| `timezone_source` | `str \| None` | AutoString | NULLable; `"inferred"` (posting-hour mode, ≥10 originals, anchored 21:00) \| `"user_confirmed"` (always wins, never overwritten) |

### Table: `posts` (`app/models/post.py:7-30`, migration:57-69 + `b7d2e5f8a3c1`)

The profile's **own** content. Ingested by the shared policy (`app/services/ingest.py`) from PFM or the user's own Xpoz handle fallback (source column records which); powers voice extraction, analytics, and baselines. Replies/retweets are routed to `user_activity`, not here — only API-flagged self-replies land with thread fields.

| Column | Model type | DB type | Constraints / notes |
|---|---|---|---|
| `id` | `int \| None` | INTEGER | PK |
| `profile_id` | `int` | INTEGER | FK → `profiles.id`, NOT NULL, index (`ix_posts_profile_id`, post.py:12) |
| `platform_post_id` | `str` | AutoString | NOT NULL; part of unique pair |
| `caption` | `str` | AutoString | NOT NULL (spec says `Text` — see divergences) |
| `published_at` | `datetime` | `UTCDateTime` | NOT NULL, **no default** — caller must pass a tz-aware value |
| `alerted_at` | `datetime \| None` | `UTCDateTime` | NULLable; set once at spike detection (alert-once) |
| `alert_dismissed` | `bool = False` | Boolean | NOT NULL; app-side default only |
| `source` | `str \| None` | AutoString | NULLable; `"pfm"` \| `"xpoz"` — which source ingested this row |
| `last_seen_at` | `datetime \| None` | `UTCDateTime` | NULLable; last complete ingest pass that saw this post (deletion-suspect bookkeeping) |
| `is_deleted_suspect` | `bool = False` | Boolean | NOT NULL, `server_default=false`; two consecutive complete-pass misses in a 30d window — **flagged and excluded, never deleted** |
| `text_truncated` | `bool = False` | Boolean | NOT NULL, `server_default=false`; caption length ≥270 with ellipsis/http tail (`ingest.py:75`, `TRUNCATION_MIN_LEN = 270`) — excluded from voice analysis, flagged for full-text fetch |
| `kind` | `str \| None` | AutoString | NULLable; `"original"` \| `"reply"` \| `"retweet"` \| `"quote"` (merged from niche Prompt 1's plan — that plan must NOT re-add it) |
| `kind_source` | `str \| None` | AutoString | NULLable; `"api"` (Xpoz structural flags present) \| `"heuristic"` (text-shape heuristics) |
| `conversation_id` | `str \| None` | AutoString | NULLable; thread grouping id when the source provides it |
| `thread_position` | `int \| None` | Integer | NULLable; 1-based position within the conversation (ingest order) |
| `is_thread_head` | `bool \| None` | Boolean | NULLable; true when position == 1 |

Constraints: `UniqueConstraint("profile_id","platform_post_id", name="uq_posts_profile_id_platform_post_id")` (post.py:9, migration:67).

### Table: `metric_snapshots` (`app/models/post.py:33-51`, migration:104-117 + `b7d2e5f8a3c1`)

Append-only; PFM/Xpoz return lifetime totals, velocity comes from deltas (`services/metrics.py:6-26`). Appended over time per the shared snapshot policy (see Profile-Extract section), so ≥2 per post accumulate for spike detection.

| Column | Model type | DB type | Constraints / notes |
|---|---|---|---|
| `id` | `int \| None` | INTEGER | PK |
| `post_id` | `int` | INTEGER | FK → `posts.id`, NOT NULL, index (`ix_metric_snapshots_post_id`) |
| `captured_at` | `datetime` | `UTCDateTime` | NOT NULL, no default |
| `likes` / `comments` / `shares` / `views` | `int \| None` | Integer | **NULLable — missing metrics are NULL, never 0** (0 drags medians/baselines/outliers). `b7d2e5f8a3c1` flipped NOT NULL→NULL and coerced legacy bogus zeros (Rule A: views==0 with any other metric >0 → NULL, 0 rows; Rule B: all four ==0 and snapshot >72h after publish → NULL, 24 rows on the real DB) |
| `age_hours` | `float \| None` | Float | NULLable; `captured_at − published_at` recorded at ingest; NULL on legacy rows (final-metrics selection recomputes from timestamps) |
| `source` | `str \| None` | AutoString | NULLable; `"pfm"` \| `"xpoz"` — the ingest source that captured it |

Constraints: `UniqueConstraint("post_id","captured_at", name="uq_metric_snapshots_post_id_captured_at")` (post.py:23) + `Index("ix_metric_snapshots_post_id_captured_at_desc", "post_id", text("captured_at DESC"))` (post.py:24, migration:117 — the only partial/expressive index besides voice's; renders correctly on both dialects).

### Table: `listening_matches` (`app/models/listening.py:8-31`, migration `46283ff46bfd:25-41`)

Third-party content surfaced by Xpoz; `profile_id` = "whose listening config matched," not the author. **Is** written now by `check_niche_trends` (tools/listening.py:166-180) and read by `GET /trends/matches` (routers/trends.py:49-55) — contrary to docs (see divergences).

| Column | Model type | DB type | Constraints / notes |
|---|---|---|---|
| `id` | `int \| None` | INTEGER | PK |
| `profile_id` | `int` | INTEGER | FK → `profiles.id`, NOT NULL, index |
| `platform` | `str = "x"` | AutoString | NOT NULL, app-side default |
| `platform_post_id` | `str` | AutoString | NOT NULL |
| `author_handle` | `str` | AutoString | NOT NULL — third-party author |
| `author_avatar_url` | `str \| None` | VARCHAR nullable | picture URL read from the handle DB right after the scan; NULL → the UI falls back to unavatar |
| `caption` | `str` | AutoString | NOT NULL; repurpose `source_text` candidate |
| `platform_url` | `str` | AutoString | NOT NULL |
| `metrics` | `dict \| None` | JSON (explicit `sa_column=Column(JSON)`, listening.py:28) | NULLable engagement snapshot; writer fills like/retweet/reply/impression counts (listening.py:173-178) |
| `discovered_at` | `datetime` | `UTCDateTime` | NOT NULL; default `datetime.now(UTC)` (listening.py:29) |
| `alerted_at` | `datetime \| None` | `UTCDateTime` | NULLable — **defined but never written** |
| `alert_dismissed` | `bool = False` | Boolean | NOT NULL — **defined but never read/written** |

Constraint: `UniqueConstraint("profile_id","platform_post_id", name="uq_listening_matches_profile_id_platform_post_id")` (listening.py:18).

### Table: `voice_profiles` (`app/models/voice.py:8-27`, migration:90-103)

Versioned voice extraction; one current row per profile (see invariants).

| Column | Model type | DB type | Constraints / notes |
|---|---|---|---|
| `id` | `int \| None` | INTEGER | PK |
| `profile_id` | `int` | INTEGER | FK → `profiles.id`, NOT NULL, index |
| `version` | `int` | Integer | NOT NULL; no default |
| `is_current` | `bool = False` | Boolean | NOT NULL, app-side default |
| `payload` | `dict` | JSON (`sa_column`, voice.py:25) | DB nullable=True; ORM default `{}` — tone/emoji/hook/vocab/structure/never-do (voice.py:24 comment) |
| `example_post_ids` | `list[int]` | JSON (voice.py:26) | DB nullable=True; ORM default `[]`; **no FK enforcement** — snapshot semantics, fine because posts are never deleted |
| `created_at` | `datetime` | `UTCDateTime` | NOT NULL; default now |

Constraints: `UniqueConstraint("profile_id","version", name="uq_voice_profiles_profile_id_version")` (voice.py:11) + partial unique `Index("uq_voice_profiles_current_per_profile","profile_id", unique=True, postgresql_where=text("is_current = true"))` (voice.py:12-17, migration:103).

### Table: `style_answers` (`app/models/voice.py:30-37`, migration:80-89)

Fallback when post history is thin. Columns: `id` PK; `profile_id` FK→profiles, NOT NULL, indexed; `question_key` VARCHAR NOT NULL; `answer` VARCHAR NOT NULL; `created_at` UTCDateTime NOT NULL (default now). **No unique on `(profile_id, question_key)`** — repeated `answer_style_questions` calls append duplicates. Written at tools/voice.py:203-207; **never read anywhere** (write-only table — see risks).

### Table: `repurpose_requests` (`app/models/repurpose.py:13-20`, migration:70-79)

| Column | Model type | Notes |
|---|---|---|
| `id` | PK | |
| `profile_id` | FK→profiles, NOT NULL, indexed | |
| `source_caption` | str NOT NULL | |
| `route_label` | `str \| None = None` | easy/standard/hard; set by `classify_difficulty` inside `app/services/repurpose_flow.py` and persisted by both callers (tool + `POST /repurpose`) since 2026-10-25 — see divergences |
| `created_at` | UTCDateTime default now | |

### Table: `repurpose_attempts` (`app/models/repurpose.py:23-37`, migration:118-134)

| Column | Model type | Notes |
|---|---|---|
| `id` | PK | |
| `request_id` | FK→repurpose_requests, NOT NULL, indexed | |
| `platform` | `str = "x"` | app-side default |
| `tier` | `str \| None` | small/large — **never written** |
| `model` | `str \| None` | **never written** |
| `provider` | `str \| None` | groq/openrouter — **never written** |
| `attempt_no` | `int = 1` | always 1 in practice; no multi-attempt writer exists |
| `output` | str NOT NULL | |
| `must_keep_passed` | bool NOT NULL | deterministic check (`services/enforcement.py`) |
| `judge_verdict` | `str \| None` | yes/no/null (judge skipped when must-keep fails, docs/models.md:38) |
| `judge_confidence` | `float \| None` | null on Llama fallback |
| `created_at` | UTCDateTime default now | |

The actual insert (tools/repurpose.py:76-82) supplies only `request_id`, `output`, `must_keep_passed`, `judge_verdict`, `judge_confidence` — everything else rides model defaults.

### Table: `user_actions` (`app/models/repurpose.py:40-47`, migration:135-144)

Append-only accept/edit/reject log. `id` PK; `attempt_id` FK→repurpose_attempts NOT NULL indexed; `action` **native enum** `useractiontype('ACCEPT','EDIT','REJECT')** (migration:138); `edited_text` VARCHAR NULL (set on edit only, tools/actions.py:26); `created_at` UTCDateTime default now.

### Table: `poll_config` (`app/models/poll.py:6-13`, migration:47-56)

One row per profile (1:1). `id` PK; `profile_id` FK→profiles NOT NULL, **unique index** `ix_poll_config_profile_id` (migration:56); `interval_minutes` int default 5; `is_active` bool default False (app-side); `last_polled_at` UTCDateTime nullable. Written by start/stop_listening (tools/listening.py:29-54), polled by `background/poller.py:23-52`.

### Table: `chat_messages` (`app/models/chat.py:14-23`, migration:35-46)

`id` PK; `profile_id` FK→profiles NOT NULL indexed; `role` native enum `chatrole('USER','ASSISTANT','TOOL')` (migration:38); `content` str NOT NULL; `tool_calls` JSON nullable (`sa_column`, chat.py:21 — populated only on assistant turns requesting tools, docs/models.md:39); `tool_name` VARCHAR nullable (role=tool); `created_at` UTCDateTime default now. Written per turn by `agent/loop.py:63-76`; history load filters out `role != ChatRole.TOOL` (loop.py:45, routers/chat.py:92).

### Table: `user_activity` (`app/models/activity.py:7-34`, migration `8c4f1a9d2e7b` + `b7d2e5f8a3c1`)

The user's **non-original** posts — deliberately separate from `posts` so replies/retweets are never attributed to the user as authored content. Unique `(profile_id, platform_post_id)`; `kind` is a plain NOT NULL string `"reply"` or `"retweet"` (no enum). Columns: `id` PK, `profile_id` FK indexed, `platform` default `"x"`, `platform_post_id`, `kind`, `caption`, `published_at`, plus profile-extract additive columns `likes`/`replies`/`views` (`int | None` — NULL when the source omits them) and `source` (`"pfm"` | `"xpoz"`). Written by `ingest.py:upsert_user_activity`; read by `get_user_activity` (tools/activity.py) and voice `reply_style` (replies only — retweet text is never fed as the user's words).

### Table: `user_search_requests` (`app/models/user_request.py`, migration `d3c4b5a6978e`)

Handles the **user explicitly asked Lumi to look up** (pasted @usernames) — deliberately separate from the peer set so a user-requested recon can never pollute `peer_frameworks` / `listening_matches`. Append-only; re-requests add rows and `already_requested` is computed at read time. Columns: `id` PK, `profile_id` FK→profiles NOT NULL + index, `handle` VARCHAR NOT NULL (normalized: no leading `@`, lowercase; validated `^[A-Za-z0-9_]{1,15}$` — garbage like `beacons.ai` is rejected, not saved), `request_note` VARCHAR nullable (the user's ask, in their words), `created_at` UTCDateTime NOT NULL (app-side default). Written by the `save_user_request` tool (`app/tools/user_requests.py`) — the tool also reports peer-set membership (sources: `DEFAULT_NICHE_HANDLES`, `peer_frameworks.payload.top_peer_handles`, `listening_matches.author_handle`) and never writes the peer stores. 0 Xpoz credits; searching a saved handle is the separate `check_niche_trends` step.

### Table: `mcp_auth_accounts` (`app/models/mcp_auth_account.py`, migration `e4f1a2b3c5d6`)

OAuth token store for MCP connectors — one row per **auth account** (`account` VARCHAR NOT NULL unique, e.g. `"google"`, shared by both Google connectors so one consent unlocks both). Columns: `id` PK, `account`, `access_token` VARCHAR NOT NULL, `refresh_token` VARCHAR NULL, `expires_at` UTCDateTime NULL, `scopes` JSON NULL, `updated_at` UTCDateTime NOT NULL. Written by `GET /mcp/google/callback` via `services/mcp.py:store_tokens` (upsert by account); read + auto-refreshed by `services/mcp.py` before every discovery/call when expired. **Tokens live only here** — never in code, docs, logs, or chat output (secrets rule). Not `profile_id`-scoped: single-user demo has one Google identity.

### Table: `peer_frameworks` (`app/models/frameworks.py:8-19`, migration `7c3e1a9b4d2f`)

`id` PK; `profile_id` FK→profiles indexed; `query`/`niche_title` VARCHAR NOT NULL default `""`; `payload` JSON NOT NULL (`sa_column`, ORM default `{}`); `analyzed_peers_count` int NOT NULL default 0; `created_at` UTCDateTime default now. Written by `discover_and_extract_niche_frameworks` and `get_peer_advice`'s scan fallback; read by `get_peer_advice`'s Chroma-first query path.

### Table: `own_post_analysis` (`app/models/analysis.py:7-32`, migration `b7d2e5f8a3c1`)

Blind-tagged analysis of the user's **own** posts — same `PostAnalysis` shape as the peer pipeline. `id` PK; `post_id` FK→posts indexed; `prompt_version` VARCHAR NULL; `analysis` JSON NULL (**NULL when pending/failed — never a fabricated analysis**); `status` `"pending"` | `"ok"` | `"failed"` default `"pending"`; `created_at` UTCDateTime default now; composite index `(post_id, prompt_version)` so prompt upgrades re-tag. Tagging is **stubbed** (`app/analysis/own_tagging.py`) until the peer Runtime Prompt A lands; bootstrap `_ensure_own_analysis` queues rows as `pending`.

### Table: `profile_snapshots` (`app/models/profile.py:23-38`, migration `b7d2e5f8a3c1`)

One row per ingestion pass: account size over time. `id` PK; `profile_id` FK indexed; `captured_at` UTCDateTime NOT NULL; `followers`/`following` `int | None` — **NULL until a profile-lookup capability is verified** (Xpoz profile lookup / PFM shape, niche Prompt 1 Step 0); `source` `"pfm"` | `"xpoz"` NULL. The row timestamps the pass even when counts are unknown — counts are never fabricated.

### Table: `profile_baseline` (`app/models/profile.py:41-60`, migration `b7d2e5f8a3c1`)

Own-account baseline: median/p75 views over recent originals. `id` PK; `profile_id` FK indexed; `window_days` int default 90; `n_posts` int default 0; `median_views`/`median_engagement`/`p75_views` float default 0.0; `baseline_reliable` bool default False (n_posts ≥ `PeerConfig.MIN_ACCOUNT_SAMPLE`); `computed_at`. Append-only — latest row per profile wins. Computed by `app.analysis.metrics` with **the same functions the peer pipeline uses** (own/peer baselines identical by construction); excludes `is_deleted_suspect` posts and posts younger than 24h. Written by bootstrap `_ensure_own_analysis` and `scripts/own_report.py`.

---

### Critical invariants

1. **One current voice profile per profile, flip-before-insert.** Partial unique index `uq_voice_profiles_current_per_profile` on `(profile_id) WHERE is_current = true` (voice.py:12-17; migration:103). `extract_voice_profile` does it correctly: load current → `is_current = False` → `session.add` → **`await session.flush()`** → compute `max(version)+1` → insert new row `is_current=True` → commit (tools/voice.py:113-138). Skipping/reordering the flush violates the index within the same transaction (docs/models.md:5-18). Version uniqueness (`uq_voice_profiles_profile_id_version`) prevents duplicate version numbers.
2. **`posts` unique `(profile_id, platform_post_id)`** (post.py:9) — same external ID may exist across profiles, never twice for one profile. Writers upsert-by-query (tools/voice.py:50-55 pattern).
3. **`metric_snapshots` unique `(post_id, captured_at)`** (post.py:23) + DESC index (post.py:24) — double-writing the same capture fails; velocity reads sort by `captured_at` in Python (`metrics.py:23`), so snapshots may be loaded unordered (`tools/listening.py:71-73` has no ORDER BY — safe because `detect_spike` sorts).
4. **Alert-once pattern, duplicated on two tables.** `posts`: writer is `check_trending` (tools/listening.py:78-84) — skip if `alerted_at is not None and not alert_dismissed`; on (re)alert it sets `alerted_at = now(UTC)` **and resets `alert_dismissed = False`**. `dismiss_alert` sets `alert_dismissed = True` only (tools/actions.py:45). Unread feed filters `alerted_at IS NOT NULL AND alert_dismissed = false` (routers/alerts.py:36-40). `listening_matches` carries the same two columns (listening.py:30-31) but **nothing implements the pattern there** — no writer, no reader, no dismiss tool for matches.
5. **`profiles.pfm_account_id` unique + NOT NULL** (profile.py:13, migration:33) — with `connect_account` never touching the DB (per CLAUDE.md), this is the guarantee that a profile row exists only after the OAuth callback.
6. **`poll_config.profile_id` unique** — DB-level 1:1; tools use select-then-insert (tools/listening.py:29-31), race-prone under concurrent starts but the unique index catches it.

### Enums and how they're stored

- `ChatRole(str, Enum)` — `USER/ASSISTANT/TOOL` with lowercase **values** `"user"/"assistant"/"tool"` (chat.py:8-11); `UserActionType(str, Enum)` — `ACCEPT/EDIT/REJECT` with values `"accept"/"edit"/"reject"` (repurpose.py:7-10).
- Both map to native SQLAlchemy enums `chatrole` / `useractiontype` (migration:38,138). Because no `values_callable` is given, SQLAlchemy persists each member's **name**, not value — **the DB stores `'USER'`, `'ASSISTANT'`, `'TOOL'` and `'ACCEPT'`, `'EDIT'`, `'REJECT'` (uppercase)**. Verified in `lumi.db`: `SELECT DISTINCT role FROM chat_messages` → `USER/ASSISTANT/TOOL`. Spec's lowercase strings are wrong for raw SQL. Round-trip through the ORM is fine (name→member lookup); `loop.py:55` sends `.value` (lowercase) to the LLM.
- On SQLite, `sa.Enum` degrades to `VARCHAR + CHECK(...)`; on Postgres it's a real enum type. Spec says `String` for both — divergence.

### Timestamp handling

- App-side UTC defaults via `default_factory=lambda: datetime.now(UTC)` (tz-aware) on: `profiles.created_at` (profile.py:14), `chat_messages.created_at` (chat.py:23), `listening_matches.discovered_at` (listening.py:29), `repurpose_requests/attempts/user_actions.created_at` (repurpose.py:20,37,47), `voice_profiles/style_answers.created_at` (voice.py:27,37).
- **No defaults** (caller-supplied): `posts.published_at`, `posts.alerted_at`, `metric_snapshots.captured_at`, `poll_config.last_polled_at`. Callers use `datetime.now(UTC)` or `datetime.fromisoformat(...)` (tools/voice.py:50,64; services/analytics.py:42,56; tools/listening.py:81,89).
- Every datetime column is `sqlmodel.sql.sqltypes.UTCDateTime`: `DateTime(timezone=True)` plus bind/result coercion to UTC. **Binding a naive datetime raises `ValueError` ("Datetime values must have timezone information")** regardless of dialect; results come back tz-aware UTC even on SQLite. So although model fields are annotated plain `datetime` (type-checker says naive is fine), the runtime schema demands awareness — `fromisoformat` on a naive ISO string from PFM would fail at commit (latent risk; Python 3.12 handles `"Z"` suffixes).
- No migration adds a `server_default=now()`; "Default now" in the spec exists only in Python. Raw-SQL inserts omitting `created_at` fail NOT NULL.

### Divergences: `.agents/database.md` spec vs actual models/migrations

1. **`Text` vs `AutoString`**: spec types `posts.caption`, `listening_matches.caption`, `style_answers.answer`, `repurpose_requests.source_caption`, `repurpose_attempts.output`, `user_actions.edited_text` as `Text`; migrations emit `AutoString` (unbounded VARCHAR on PG) — cosmetic on PG, but literal spec mismatch.
2. **`role`/`action` as `String`**: spec says `String` with lowercase values (database.md:175,151); actual are native enums storing **uppercase names** (verified in DB). Raw SQL `INSERT ... VALUES ('user')` would violate the PG enum/CHECK.
3. **"Default now / Default false / Default 0" are not DB defaults**: every such column is NOT NULL with **no `server_default`** in the migrations (e.g. profiles.created_at migration:31, posts.alert_dismissed migration:64, metric likes migration:108). Defaults live only in SQLModel field args; spec implies DB-level defaults.
4. **posts unique stated as "Unique index"** (database.md:43); actual is a `UniqueConstraint` named `uq_posts_profile_id_platform_post_id` — functionally equivalent, different catalog object; `listening_matches` same.
5. **Alert-once implementation differs**: spec shows an atomic `UPDATE ... WHERE alerted_at IS NULL` (database.md:30-31); actual is a Python read-check-write with per-post commit and an extra `alert_dismissed = False` reset (tools/listening.py:78-84). Works, but not concurrency-safe (two overlapping `check_trending` runs can double-alert).
6. **"Seeded with 3 demo accounts" (database.md:17) is stale**: `seed.py` now upserts a single developer profile (`AtehOfficial`, hardcoded PFM id, seed.py:11-12,43-48) and **purges nothing** — the docstring promises "purging all third-party accounts" but no delete code exists (§4); CLAUDE.md's "three seeded demo profiles" is equally stale.
7. **`listening_matches` "nothing populates it yet" (docs/models.md:33, implied by database.md:64's "integration status") is false**: `check_niche_trends` inserts matches (tools/listening.py:166) and `/trends/*` reads/scans them (routers/trends.py:43-86). Docs lag the code.
8. **`route_label` "set by the agent (classify_difficulty tool) or by Python rules" (database.md:114)**: there is still no `classify_difficulty` *tool*, but since 2026-10-25 the column **is** populated — `app/services/repurpose_flow.py:85-86` calls the service function `classify_difficulty(...)` and both the tool and `POST /repurpose` write `outcome.route_label`. **Resolved** (spec wording about a tool is still unimplemented by design).
9. **`repurpose_attempts.tier/model/provider`** documented as populated ("Actual model ID used", "groq, openrouter", database.md:133-135) — **resolved 2026-10-25**: `repurpose_flow.AttemptRecord` carries `tier`/`model`/`provider`/`attempt_no` from every generation attempt and both writers persist them, with `attempt_no` reaching 2 on a judged retry.
10. **`chat_messages.content` and `repurpose_attempts.must_keep_passed`** have blank constraint cells in the spec (database.md:176,138) but are NOT NULL in both model and migration.
11. **`voice_profiles.payload`/`example_post_ids`** — spec lists them as plain JSON (nullability unstated); DB has nullable=True while the ORM always materializes `{}`/`[]`.

Models vs migrations: **no model↔migration drift found** — every model column, constraint, and index (including the partial index and both JSON `sa_column`s) appears identically across the eleven revisions (`2fe84cc3dec6` … `b7f3a91c5d20`), and `alembic current` = `b7f3a91c5d20` (head, 21 tables) as of 2026-10-27. `alembic check` **passes** (exit 0) since 2026-10-26: `alembic/env.py` gained an `include_object` hook that skips the one known expression index (`ix_metric_snapshots_post_id_captured_at_desc`) on SQLite only — SQLite cannot round-trip expression indexes, so reflection reported a false "changed index" that autogenerate would have answered by dropping/recreating it; Postgres still compares it for real. The profile-extract migration was copy-tested **up and down** on a copy of real data before being applied.

### Risks, bugs, inconsistencies

- **BUG (SQLite portability) — FIXED 2026-10-26:** the voice partial unique index used to silently degrade on the actual dev DB. It was declared only with `postgresql_where` (voice.py:16, migration:103); SQLite ignored the dialect-specific kwarg, so `lumi.db` held `CREATE UNIQUE INDEX uq_voice_profiles_current_per_profile ON voice_profiles (profile_id)` — **no WHERE clause** — making a second voice-profile version fail with IntegrityError even when the flip-before-insert+flush order was correct. Now: `sqlite_where=text("is_current = 1")` on the model + revision `2f30380b96df` rebuilds it on existing SQLite databases (one-way; downgrade is a no-op by design). Locked by `tests/test_voice_index_sqlite.py`.
- **Write-only / dead columns**: `style_answers` rows are inserted (tools/voice.py:205) but **never selected** by any tool/router/service — the "thin history fallback" stores answers nobody reads. `repurpose_attempts.tier/model/provider` and `repurpose_requests.route_label` were also dead until `repurpose_flow` landed (2026-10-25) — both are written now. Still never written **and** never read: `listening_matches.alerted_at/alert_dismissed` (`dismiss_alert` handles `Post` only, tools/actions.py:39-49).
- **Nullable-vs-required mismatch latent risk**: `posts.published_at` / `metric_snapshots.captured_at` accept only tz-aware datetimes at runtime (UTCDateTime bind check), but are annotated naive `datetime` with no static enforcement; a naive `fromisoformat` result from PFM (services/analytics.py:42, tools/voice.py:50) would explode at commit.
- **`profiles.handle` has no unique constraint** while seed idempotency and UI selection key on it (seed.py:34); the case-variant set `{"AtehOfficial","atehofficial","just_ateh"}` (seed.py:11) hints at prior dedup pain. DB will happily hold duplicate handles.
- **Underused index**: `ix_metric_snapshots_post_id_captured_at_desc` exists for "velocity queries", but both hot paths (check_trending tools/listening.py:71-73, unread alerts routers/alerts.py:46-48) load *all* snapshots per post with no ORDER BY/LIMIT and sort in Python — N+1 per check; the DESC index never fires. Also `chat_messages` history orders by `created_at` with only a `profile_id` index (loop.py:46).
- **`style_answers` has no unique `(profile_id, question_key)`** — re-answering questions duplicates rows with no upsert guard.
- **Encoding**: no mojibake in models/migrations/docs; `listening.py:11` contains a genuine em dash (U+2014, bytes `E2 80 94`). It only *renders* as U+FFFD on Windows cp1252 consoles — a display artifact, not file corruption.
- Minor: `check_trending` commits inside the per-post loop and again for `last_polled_at` (listening.py:84,91) — multiple commits per invocation, fine for a demo, fragile for rollback; `seed.py` swallows all exceptions (seed.py:59-60), hiding seed failures.

*(~270 lines)*
---

## Profile-Extract Data Quality (landed 2026-10)

The profile-extract data-quality overhaul (Steps 1–3 of `C:\Users\USER\Downloads\profile_extract_fixes.md`, on top of the Step 0 audit in `docs/profile_extract_audit.md`). **Status: landed and verified** — migration applied to the real DB, 148 tests green, server smoke-tested. Everything remains **uncommitted** until explicitly requested.

**What it does:** one shared ingestion policy (`app/services/ingest.py`) now owns classification, truncation, deletion-suspect detection, snapshot scheduling, and timezone inference — so PFM deep backfill, PFM incremental refresh, Xpoz own-posts fallback, and the voice tool's opportunistic backfill all behave identically by construction (`store_raw_item` is the single `MetricSnapshot(` construction site, `ingest.py:423`).

**Where things live:**
- **`app/services/ingest.py`** — `classify_post_item` (replies/RTs → `user_activity`, originals → `posts`; heuristic `@handle`-openers incl. self-mentions classify as replies; only the API-flag path via `PostFlags.has_structure` routes self-replies to `posts`), `store_raw_item`, snapshot policy (milestones 24h/72h/7d/30d, min 6h gap when unchanged, skip unchanged >7d unless a milestone crosses; `TARGET_SNAPSHOT_AGE_HOURS=72.0`, `MILESTONE_AGES_HOURS=(24,72,168,720)`, `MIN_REFRESH_GAP_HOURS=6.0` in `app/analysis/metrics.py:27-30`), deletion-suspect detection (`DELETION_WINDOW = 30` days, `ingest.py:41` — two consecutive complete-pass misses; conservative "no" when the window is unknown; **flagged/excluded, never deleted**), truncation flag (`TRUNCATION_MIN_LEN = 270`, inclusive with ellipsis/http tail, `ingest.py:43`), weak timezone inference (`MIN_TZ_POSTS = 10`, `ingest.py:42` — mode of posting hour anchored 21:00; `user_confirmed` always wins), and profile snapshots.
- **`app/analysis/`** — `metrics.py` (shared own/peer baselines), `lift.py`, `own_tagging.py` (stubbed `status='pending'` until the peer Runtime Prompt A merges), `own_lift.py` (skips `is_deleted_suspect` posts; `compute_own_lift(persist_baseline=False)` default, bootstrap passes `True`).
- **`app/services/analytics.py`** — rewritten: `_ingest_pfm_feed` (`:36`) / `_ingest_xpoz_user_posts` (`:84`) / `get_profile_analytics` (`:141`); NULL metrics coerced `or 0` **for display only**; fabricated demo branch removed (honest zeros/empties + `is_live_data: False`); posts paired with snapshots by `post_id`, never positional `zip`.
- **`app/tools/`** — `backfill.py` (`backfill_posts` tool), `activity.py` (`get_user_activity`), `advice.py` (`get_peer_advice`), `memory.py` (`remember`/`recall_memory`).
- **`app/background/bootstrap.py`** — 4 ordered steps (0 corpus, 1 voice, 2 peer, 3 own analysis); `_ensure_own_analysis` is the **last** step and passes `persist_baseline=True`.
- **`scripts/own_report.py`** — read-only data-quality report (verified against the real DB: profile 16 = 24 NULL snapshots fixed → `insufficient_data`; profile 2 = 15 originals, 9 replies, 6 winners, `status=ok`).
- **`app/routers/profiles.py`** — `GET /profiles` now serializes `timezone`/`timezone_source` (currently null until inference runs).

**Migration `b7d2e5f8a3c1`** (`down_revision='8c4f1a9d2e7b'`) — copy-tested up **and** down on a copy of real data, then applied to the shipped `lumi.db` (`alembic current` = head). Data fixes: **Rule A** (views==0 with any other metric >0 → all NULL; 0 rows) + **Rule B** (all four metrics ==0 AND snapshot >72h after publish → all NULL; 24 rows, all profile 16). Downgrade is **partially destructive by design**: NULL metrics coerce back to 0 (documented in the file header); booleans/strings drop.

**Key decisions (from the spec):** missing metrics are NULL, never 0 (no fabricated fallbacks — flagged gaps stay flagged/pending); niche Prompt 1's planned `kind`/`kind_source`/`conversation_id` columns on `posts` were merged into this migration (that plan must not re-add them); own and peer baselines use the same `app/analysis/metrics.py` functions (identical by construction); own tagging stays `status='pending'` until the peer Runtime Prompt A merges; `kind_source` = `"api"` when `PostFlags.has_structure`, else `"heuristic"`; `final_metrics` = snapshot nearest 72h (age recomputed from timestamps when legacy `age_hours` is NULL); voice replies feed `reply_style` only, retweet text never attributed to the user; Xpoz results still never enter `posts` from third-party sources — only the user's own handle via the own-posts fallback, flagged `source="xpoz"`.

**Known gaps / caveats:** **PFM is on hold — the API key is expired** (401s in this environment), so all PFM ingestion paths are parked until the key is renewed; the Xpoz own-posts fallback is the working alternative meanwhile. Xpoz user-search endpoint (`/api/data/twitter/users/live`) is verified working (the older post-search path was the flaky-401 one); `docs/xpoz_capabilities.md` is missing so there's no full-text fetch for truncated posts (flag + exclusion kept); own tagging is `status='pending'` until the peer Runtime Prompt A merges (niche/peer Prompts 1–3 gated on the user's credit-cost go). Xpoz free plan = 500 credits **one-time**; "1 tracked keyword/user" is a continuous-monitoring slot, not a query cap — the bottleneck is purely credits (X/Reddit = 2 credits/query), and `/api/plan` + `/api/usage` need a dashboard session so client-side counting is the only credit meter. The credit-aware @-handle bar lives in the **handle-search MVP** (`mvp/handle_search/`) — see below and `docs/xpoz_optimization.md`.

---

## @-handle Search MVP (built 2026-10; wired into the main app 2026-10-21; multi-platform selector 2026-10-25)

A real-time @-mention handle-search bar, born as a **standalone side project** at `mvp/handle_search/` (FastAPI, port 8010 — still runnable on its own). **Since 2026-10-21 it is wired into the main app:** `app/routers/handles.py` is a thin delegation shim (4 routes under `/handles/*`, registered in `main.py` as the 7th router) that calls the MVP's own endpoint functions (`api_search` / `api_saved` / `api_select` / `api_stats`) — the MVP core stays the single source of truth, there is zero logic duplication, and the main frontend talks to ONE API base. In the chat composer (`C:\Users\USER\Downloads\lumi\frontend`, `PromptBar.tsx`): typing `@` + ≥2 chars opens the real handle menu (avatars, follower counts, db/cache/live source badges; instant 0-credit snapshot paint + 300 ms debounced refine with a stale-response guard; breathing skeleton while pending, breathing dot behind painted rows); a **multi-select platform selector** (added 2026-10-25) renders a pill row — X · Instagram · TikTok · Reddit · LinkedIn — above the menu rows in **both** UIs (PromptBar + the standalone bar): every ticked platform is searched (the server fans out per platform, charging that platform's credits; at least one pill stays ticked), non-X rows carry a platform chip and a platform-specific `unavatar.io` fallback, and toggling re-fetches the saved snapshot + re-runs the open `@` search; picking a handle **inserts `@handle ` into the composer — the user types their own ask and sends** — and fire-and-forget POSTs `/handles/select` (with the row's `platform`); the `+` button keeps the old demo SOURCES list; sending flows into the existing agent path (prompt rule 13: `save_user_request` → `check_niche_trends`; rule 13 also treats a message that is *nothing but* `@handles` as a lookup request, and the claim gate's `_BARE_HANDLES_RE` enforces it). The main app also **feeds its handle DB**: every Chronic-Online/niche search persists the users it touched (`app/services/handle_db.py`, see below). Plan + rollout: `docs/xpoz_optimization.md` §5–§6; flow map: `docs/flow-map.md` / `.html` §4.

**What it does:** a normal text bar arms on `@`, and at ≥2 chars (300 ms debounced) searches users with profile pictures + handles. Saved handles paint **instantly** from an in-browser snapshot (0 ms, 0 credits); then the server resolves — cache-first so it saves Xpoz credits but **never locked to cache**:

1. `lumi.db` (read-only) — prefix-match on `profiles.handle` + `listening_matches.author_handle` (0 credits);
2. Chroma `handle_mappings` — every handle ever **pulled, selected, or fed by a main-app search** (pfp + name + followers), prefix match (0 credits);
3. Chroma `handle_cache` — past results + **prefix-chain reuse** (ka→kar→karp = one query), fresh for `MVP_CACHE_TTL_MINUTES` (default 60);
4. Xpoz `users/live` **per selected platform** (X/Reddit **2**, TikTok **5**, Instagram **12** credits/query — exact paths/params/fields verified against the live OpenAPI spec: `q` for X/Reddit, `name` for IG/TikTok) — fires **whenever that platform has no fresh cached answer** (miss or stale → real-time refresh, `refreshed: true`); credit-budget-guarded (one fan-out charges the sum, stopping honestly when the next platform's cost won't fit), two keys with rotation. **LinkedIn has no Xpoz endpoint** (the spec covers X, Instagram, Reddit, TikTok only) — it stays selectable as an honest db/remembered-only platform (`platform_reasons.linkedin = "unsupported"`, 0 credits, never a fabricated live source). Every result row carries `platform`; caches, the remembered store, and the X-only local-db layer are all platform-filtered (pre-2026-10-25 rows default to `x` — that is all that existed).

**The DB is a head start, never the answer:** layers 1–2 merge into the results (and paint instantly client-side) but **never gate the live search** — only a fresh *cache* entry (a real recent search) may skip live. Otherwise `@ateh` would show only the one Ateh saved in the db instead of the actual people currently on X. The dropdown is a **half-and-half mix** by *where each handle came from on this search*: about half the slots go to the **saved half** — everything served from memory (local db / remembered / past-search cache), with local-db handles such as `@AtehOfficial` leading it — and half to the **live half**, what a fresh Xpoz pull just returned; a side short of half hands its leftover slots to the other so the list still fills to ten, and the exact handle you typed stays at the very top. So a known handle like `@AtehOfficial` is always visible beside fresh results instead of sinking behind higher-follower strangers — and a memory-served handle can never crowd a fresh-pull one out of view, because they sit in different halves. When live is off or the budget is spent, the saved half still answers — it is the help, not the source. A db miss shows a **breathing skeleton** (in/out pulse) while the real search runs; behind db-served rows a small breathing dot signals the refinement in flight.

**The handle DB expands on every search:** every live pull persists *all* returned handles — picture, display name, follower count — into `handle_mappings` with `origin: live | cache | selected | niche`, not just the one the user selects. A stale cached entry triggers a budget-guarded re-query instead of serving frozen results forever; a fresh *empty* entry (negative cache) never re-burns credits.

**Main-app side (`app/services/handle_db.py`):** the same `handle_mappings` collection is written by the main app — `check_niche_trends` persists every tracked account **and every author its posts surfaced**, `discover_and_extract_niche_frameworks` persists every search-result author (`origin: niche`). Add-if-absent (fresher live/selected rows and their labels are never overwritten), never raises, no-op without `MVP_CHROMA_*`. Tracked accounts unknown to the store get a **bounded enrichment** via the verified Xpoz user search (picture/name/followers, ≤2 credits each, **exact username match only** — a fuzzy top-hit is another person and their picture is never stored; cap `HANDLE_DB_ENRICH_LIMIT`, default 6 per call, `0` disables). Keyword-search authors are saved handle-only (unbounded enrichment would burn dozens of credits); their picture still displays via the unavatar fallback and followers stay NULL — never fabricated.

**Isolation & config (all in `.env`, gitignored — never in code/docs):** dedicated `MVP_CHROMA_API_KEY/TENANT/DATABASE` (database `Onscript`) so the main app's `CHROMA_*` voice-corpus storage is never repointed; `XPOZ_API_KEY` + `XPOZ_API_KEY_2` (rotation on 401/402/403); `MVP_XPOZ_BUDGET` (default **100 live-search credits**/session since 2026-10-25 — a query charges its platform's price: X/Reddit 2, TikTok 5, Instagram 12; the fan-out stops when the next platform's cost won't fit); `MVP_XPOZ_LIVE` (kill-switch); `HANDLE_DB_ENRICH_LIMIT` (new scanned handles enriched per scan, default 6, `0` off); `HANDLE_SEARCH_DB` (defaults to `lumi.db`, read-only). Endpoints: `GET /` (bar), `GET /api/handles/search` (`?platforms=` CSV = `x|instagram|tiktok|reddit|linkedin`, default `x` — server fans out per platform; `?context=` = up-to-3 words before the `@`, re-ranks results, never sent to Xpoz), `GET /api/handles/saved` (`?platforms=` filter — instant-suggest snapshot: db ∪ remembered — the browser prefix-filters it per keystroke for a 0-credit first paint while the debounced full search refines), `POST /api/handles/select` (accepts `platform`), `GET /api/handles/stats` (credit meter incl. `credits_spent_this_session` + combined `saved_handles` count + per-origin handle counts + TTL + the `available_platforms` catalog the pill rows render from).

**Tests:** `tests/test_handle_search_mvp.py` — Xpoz fully mocked, green with no network; covers the db-as-head-start merge (db hits never gate live), the free db fallback when live is off, cache/prefix reuse, live-on-miss, TTL real-time refresh (stale → re-query; fresh negative cache → no re-burn; stale + budget spent → honest fallback), key rotation, auto-persistence of every live pull, context ranking from the words before the `@`, the half-and-half mix by origin — saved half (memory-served rows, local db leading) vs live half (fresh-pull rows), exact typed handle first, a short side backfilled so the list still fills to ten — a db handle keeps its slot even when a richer remembered copy overwrites its `source`), the combined `saved_handles` count, and the credit-free `/api/handles/saved` snapshot. `tests/test_handle_search_platforms.py` (14 tests, added 2026-10-25) — the multi-platform layer: per-platform fan-out paths/params (`q` for X/Reddit, `name` for IG/TikTok) with field normalization (IG `fullName`/`profilePicUrl`, TikTok `nickname`/`avatar`, Reddit NULL followers), `platforms` CSV validation, cache isolation per `platform:query` key, the local-db layer feeding X searches only, LinkedIn reported honestly `unsupported` (0 credits, never a live source), credit budget stopping an expensive platform mid-fanout (X+Reddit charged, Instagram not), `/saved` platform filtering, the `available_platforms` stats catalog, a default selection stamping `platform: "x"` on legacy rows, and the two **Chroma Cloud quota fixes found in live smoke 2026-10-25** — a fat (Instagram-sized) pull trimmed into the 8,182-byte `MetadataValueSizeBytes` limit (pre-fix the write was rejected and every search re-burned 12 credits) and cache reads offset-paged past the 300-row `LimitValue` Get cap (pre-fix unfiltered reads silently returned the oldest 300 rows while the handle DB held 637, hiding new handles from `/saved`, the merge and stats). `tests/test_handle_db.py` — the main-app side: MVP-compatible row shape, add-if-absent, enrichment rules (exact match / cap / off), never-raises, and both listening tools wired (every scanned handle + author persisted, scan survives a handle-DB failure).

---

## MCP Connectors (Google Drive + Docs first — landed 2026-10-21)

Lumi runs **its own in-backend MCP client** (official Python `mcp` SDK, pinned `mcp==2.3.0` in `pyproject.toml`, Streamable HTTP transport). Anthropic's cloud-side MCP connector only exists on Anthropic's API; this agent runs on Groq/OpenRouter behind the OpenAI SDK, so connector tools are discovered over MCP and converted to OpenAI-style function specs for the same tool-calling loop — no provider switch, no Anthropic key, and localhost/stdio servers stay reachable later (a cloud connector can never reach them). Deliverable docs (architecture diagram, **adding another connector in one config entry**, manual Google Cloud setup checklist, live verification script, env reference): **`docs/mcp-connectors.md`**.

**Where things live:**
- **`app/services/mcp_connectors.py`** — the **config-driven connector registry**: one `MCPConnector` entry per connector (`name`, server `url`, `auth` = `google_oauth`|`bearer_env`|`none`, `scopes`, `allowed_tools` allowlist, `confirm_writes`, `enabled_env` kill switch). Adding a connector = one entry here, never code elsewhere. Google URLs are verified, not guessed: Drive `https://drivemcp.googleapis.com/mcp/v1`, Docs `https://docsmcp.googleapis.com/mcp/v1`; consent `https://accounts.google.com/o/oauth2/v2/auth`, token `https://oauth2.googleapis.com/token`.
- **`app/services/mcp.py`** — the client: per-connector `tools/list` discovery (TTL cache `MCP_TOOLS_TTL_SECONDS` 300s, per-turn budget `MCP_REFRESH_TIMEOUT_SECONDS` 15s), OpenAI-spec conversion (names sanitized to `mcp__<connector>__<tool>` over `[A-Za-z0-9_-]`, allowlist-filtered, originals kept for dispatch), `tools/call` dispatch under `MCP_CALL_TIMEOUT_SECONDS` 60s (inside the loop's 120s per-tool cap), Google token load/refresh (auto-refresh when expired, uses `refresh_token`), and the **write-confirmation gate**.
- **`app/routers/mcp_google.py`** — `GET /mcp/google/connect` (302 to consent with `access_type=offline` + `prompt=consent` + scope union; honest 503 `google_oauth_not_configured` when client env vars are unset), `GET /mcp/google/callback` (code→token exchange, upserts `mcp_auth_accounts`, JSON response — same browser-JSON UX gap as the PFM callback), `GET /mcp/google/status` (`connected` / scopes / expiry / **`configured`** — are the OAuth client env vars set at all; added 2026-10-21 so the frontend's Settings → Connectors card can explain an unconfigured server instead of offering a dead connect button).
- **`app/models/mcp_auth_account.py`** + migration `e4f1a2b3c5d6` — token store table (see Data Model section); tokens live only in the DB.
- **`app/tools/registry.py`** — `list_tool_specs()` appends the cached `mcp__*` specs (best-effort); `call_tool()` routes `mcp__*` names into `app/services/mcp.py`.
- **`app/agent/loop.py`** — per turn: TTL-gated `refresh_tools()` at turn start (never raises — a dead MCP server degrades to "connector absent", prompt rule 16 makes the model say Google isn't connected); before the model speaks, resolves a pending write from the previous turn (clear yes → execute, inject the real outcome as a system note + TOOL row + `tool_calls_made`; anything else → cancel note) and the gate-regex families (`_COMPLETED_ACTION_PATTERNS`/`_PROMISE_ACTION_PATTERNS`) cover doc-creation claims ("I've created the doc", "I drafted a document") so zero-tool fabrications of doc work are nudged.
- **`app/agent/prompts.py` rule 16** — plain-language routing ("make a doc" → connector tools; the `#doc`/`#drive` composer prefills in `PromptBar.tsx` produce exactly these asks), the **confirmation protocol** (never claim a write happened before the user confirms; report the real outcome after), and "if no `mcp__*` tools are in your toolset, say Google isn't connected" honesty.
- **Scopes** — both connectors share **one** auth account `"google"` and **one** consent granting the union: `drive.readonly` + `drive.file` (narrow write scope: only files this app creates — a confirmed write can never touch the user's other files) + `documents`.

**Key correctness properties:** config-driven (connector = registry entry); explicit user confirmation before any write/edit/delete tool runs (word-wise write-verb classifier — `get_file_created_time` is NOT gated; "yes, but later"-style deferrals veto execution; the pending write lives in process memory, single-worker app, and is always resolved by the user's next message — never stale); allowlist restricts exposed tools at discovery time; failures are honest `{error}` payloads, never raised 500s; unauthenticated/unreachable connector → no tools + honest "not connected" reply. Tests: `tests/test_mcp.py` + `tests/test_mcp_google_router.py` (32 tests; discovery/dispatch/gate/refresh/router seams all faked — no sockets, no Google calls) + doc-gate regressions in `tests/test_agent_claim_gate.py`. Zero-credit smoke verified 2026-10-21: `/health` 200, `/mcp/google/status` `connected:false` + `configured` flag, `/mcp/google/connect` honest 503.

**Blocked on the user's manual setup:** the live script "List my 5 most recently modified Drive files" needs the GCP checklist in `docs/mcp-connectors.md` §3 done first (client id/secret env vars + one consent visit). Nothing in this work burns Xpoz credits or touches PFM.

---

## Peer-Framework Pipeline Upgrade (built — Prompts 1–3 complete 2026-10-26)

Replacing the absolute-threshold peer-framework extraction with a baseline-relative, lift-table pipeline. **Status: COMPLETE and wired 2026-10-26.** Both live entry points (`discover_and_extract_niche_frameworks`, bootstrap `_ensure_peer_frameworks`) now run `app/services/peer_pipeline.py`; the old path (`impressionCount ≥ 1000` → `posts[:20]` → one-shot LLM → canned "Milestones & Shipped Tech" fallback) and `app/services/frameworks.py` itself are **deleted** — `grep -rn "Milestones & Shipped Tech" app/ tests/` finds nothing. Source plan: `C:\Users\USER\Downloads\opencode_prompts.md` (Prompts 1–3, each staged and gated on review).

### Where things live

- **Schemas: `app/schemas/peer.py`** (landed, +8 tests in `tests/test_peer_schemas.py`). Provenance tiers — `scraped` (Xpoz API) → `computed` (code only, never the LLM) → `llm_inferred` (prompt output) → synthesis:
  - `PeerConfig` — `SCAN_POSTS_PER_ACCOUNT=60`, `MIN_ACCOUNT_SAMPLE=30`, `MIN_POST_AGE_HOURS=24`, `LOOKBACK_DAYS=28` (**changed 2026-10-26** from 90: the baseline is now the account's recent 4 weeks, and the constant is shared with the own-post side so both baselines stay identical by construction), `TOP_N_WINNERS=20`, `MAX_WINNERS_PER_ACCOUNT=5`, `MIN_OUTLIER_FOR_WINNER=1.5` (**the only bar** — `MIN_VIEWS_FLOOR=500` was removed the same day: a fixed absolute floor judged small accounts by a big account's numbers, and a 0.5×-median floor could never exclude a post the 1.5× test had already passed), `MIN_N_FOR_LIFT=3`, `LOW_CONFIDENCE=0.6`, `BATCH_SIZE=8`, `MIN_WINNERS_FOR_REPORT=8`.
  - computed: `AccountBaseline` (median/p75 views, median engagement, posts/week, reliability flag) and `PostMetrics` (ER, outlier vs own median, reply/repost/bookmark-to-like, format + char/line/thread/hashtag/emoji counts, day/hour + posting-gap timing, exclusion flags: pinned/reply/repost/boosted-suspect/<24h; `quotes`/`bookmarks` are `Optional[int]` — never default missing metrics to 0).
  - LLM output: `HookAnalysis`, `BodyAnalysis` (+`PASDetail`/`AIDADetail`/`StoryDetail`; validator enforces detail-block ↔ primary-framework match), `CTAAnalysis`, `VoiceAnalysis`, `StrategyAnalysis` → `PostAnalysis`/`PostAnalysisBatch`; `PostTagging` persistence wrapper (`status: pending|ok|failed`, low-confidence `framework_guess`, `validation_error`, `prompt_version`).
  - synthesis: `LiftRow`, `WinningFramework`, `SynthesisOutput`, `NicheFrameworkReport` (`status: ok|insufficient_data|failed` — **a failed report must carry NO fabricated frameworks**).
- **Built so far:** `app/analysis/metrics.py` + `lift.py` (shared with the own-post side — both docstrings say the peer pipeline consumes them) and **`app/analysis/winners.py` (added 2026-10-26, +12 tests in `tests/test_peer_winners.py`)**: `ScrapedPost` (a normalized adapter shape, because the Xpoz `fields` contract is still unverified — adapters translate instead of the pipeline reading raw API JSON), `build_account_baseline` (same exclusion + percentile math as own posts), `build_post_metrics`/`build_account_metrics` (the computed tier: outlier vs own median, engagement ratios, timing gaps), and `select_winners` (blind and baseline-relative: `outlier ≥ 1.5×` own median — **the only bar**, no absolute views floor, pinned/reply/repost/boosted-suspect/<24h excluded, ≤5 per account, top 20, and **< 8 winners ⇒ `insufficient_data` with thresholds never lowered**; unreliable or missing baselines drop the account with a recorded warning).
- **Built 2026-10-26 — `app/analysis/extract.py` (blind tagging):** `build_tagging_messages` sends **ids + text only** (a test asserts no `views`/`outlier`/`likes`/`winner`/`engagement` key ever rides the payload), `tag_posts` batches `PeerConfig.BATCH_SIZE` posts through `chat_completion_with_fallback(..., [])` and validates the reply as `PostAnalysisBatch`; junk output, a post missing from the response, or a provider error all become `PostTagging(status="failed")` rows carrying the reason — an analysis is never invented. Confidence below `LOW_CONFIDENCE` keeps the model's original guess in `framework_guess`, and `lift_attributes()` mixes the tagged structure with the computed `format` from `PostMetrics`.
- **Built 2026-10-26 — `app/analysis/synthesize.py` (grounded narrative):** `build_synthesis` reports a framework only when its lift row is `reported` and `lift >= 1.5` (structure from `STRUCTURE_BY_FRAMEWORK`, evidence = winner post ids actually carrying it, confidence = mean tagging confidence, `LOW_CONFIDENCE` when there is no evidence), pillars from reported `content_pillar` rows with `lift >= 1`, whitespace = `lift >= 1.5` with `baseline_share <= 0.2`; empty results come back as warnings, never filler. `build_report` sets `status` honestly — `insufficient_data` (selection short) and `failed` (no usable tagging) both leave `synthesis = None`, so **a failed report carries no frameworks**. Tests: `tests/test_peer_extract.py` (13), `tests/test_peer_synthesize.py` (8).
- **Built 2026-10-26 — Prompt 2 (persistence):** migration `cefd455456a2` adds `niche_framework_reports` (one JSON `NicheFrameworkReport` per row — same pattern as `peer_frameworks.payload` — with `status`/`posts_analyzed`/`winner_count` mirrored out for querying) and `post_taggings` (unique `(post_id, prompt_version)`; `analysis` JSON stays NULL on failure), written through `app/services/peer_store.py`: `save_report`, `save_taggings` (upsert), `latest_report`, `cached_taggings` (only `status="ok"` rows are reused, so failures retry on the next run) — stale rows parse to `None` instead of raising. Persistence is best-effort: an analytics write never fails the tool call. Chroma (`peer_frameworks`, `peer_posts`) stays a derived, exception-shielded index. Tests: `tests/test_peer_store.py` (7).
- **Built 2026-10-26 — Prompt 3 (wiring + fallback deletion):** `app/services/peer_pipeline.py` orchestrates fetch → baseline → winners → blind tagging (with `(post_id, prompt_version)` cache) → lift → synthesis → persistence, exposing `run_peer_pipeline`, `legacy_payload_from_report` (the `peer_frameworks`/Chroma bridge: frameworks/pillars strictly from the report, `percentage_of_posts` kept 0 because the report does not measure it) and `winner_post_dicts`. Both call sites run it; `app/services/frameworks.py` is deleted. Tests: `tests/test_peer_pipeline_wiring.py` (2) + the reworked `test_xpoz_resilience.py` / `test_handle_db.py` coverage.
- **Still blocked (external):** Xpoz `fields` verification (`docs/xpoz_capabilities.md` — pinned/post detection and follower counts are unknown, so `is_pinned` is currently always False) and the credit estimate for the per-account scan fan-out (≤8 accounts × 60 posts per run).

### Pipeline (live since 2026-10-26)

discovery: keyword search → distinct author handles, ≤8 accounts [Xpoz `search_live_posts`; every search-result author also feeds the handle DB] → fetch ~60 recent posts/handle [Xpoz `get_user_live_posts_page`, cursor-paginated; undated/textless posts dropped] → per-account baseline [computed, 28-day window, shared with own posts] → per-post metrics + outlier scores [computed] → winner selection: outlier ≥1.5× **own** median (the only bar), exclusions applied, ≤5 winners/account, <8 winners → `status=insufficient_data` (thresholds never lowered to fill quota) [computed] → **blind** LLM tagging of ALL posts — no metrics in the prompt, cached by `(post_id, prompt_version)` [llm] → lift table winners vs baseline [computed] → narrative synthesized from lift rows only, each claim backed by a row [derived from rows, no LLM] → `NicheFrameworkReport` persisted [`niche_framework_reports` + `post_taggings`, plus the derived `peer_frameworks`/Chroma bridge].

Key correctness properties: baseline-relative winners instead of absolute impressions; blind tagging (the LLM never sees performance); verbatim-slice verification against original text to kill hallucinated quotes; cache by `(post_id, PROMPT_VERSION)` so upgrades re-tag; missing scraped metrics recorded as `None` + warning, never 0.

### Audit fixes vs the source schema file

`emoji_count` added (item 6); timing fields `day_of_week`/`hour_utc`/`hours_since_prev`/`hours_to_next` added (item 8); `quotes`/`bookmarks` made `Optional[int]` (Xpoz availability unverified — `quoteCount` isn't even in the current `fields` param); `MIN_WINNERS_FOR_REPORT=8` added; `PostTagging` added so a failed post is representable without inventing an analysis; converted to repo `X | None` style.

### Open items

- `body_structure_knowledge.md` not yet in the repo (reference doc only — Runtime Prompt A is self-contained, so this doesn't block Prompt 1).
- Xpoz: verify `fields` supports `bookmarkCount`/`quoteCount`/follower counts; credit budget guard (`XPOZ_RUN_CREDIT_BUDGET`) and 12h idempotent cache are Prompt 1 decisions (report estimated credits/account/snapshot before wiring).
- Audience-response analysis (item 9: top reply themes/objections) deliberately deferred from v1.

---

## Niche Extraction Pipeline Upgrade (staged — schema landed 2026-10)

Deriving the niche, location, queries, and peer handles from the user's own profile extract instead of hardcoded defaults. **Status: schemas landed + tested; pipeline NOT wired.** Today the niche query and handle lists are constants (`DEFAULT_NICHE_QUERY` in `bootstrap.py`; `DEFAULT_NICHE_HANDLES` now lives in `app/agent/prompts.py` as the single source of truth, imported by `bootstrap.py` and `tools/user_requests.py`), there is no location data anywhere (only "regional niche" prose in prompts), replies in `user_activity` are bare text with no parent, RTs are stored but unread, and comments are never fetched. Source plan: `C:\Users\USER\Downloads\niche_opencode_prompts.md` (Prompts 1–3, each gated on review; **Prompt 1 starts with an Xpoz capability report — profile lookup, reply parents, and comment fetching are unverified assumptions, don't build on guesses**).

Flow: profile extract → niche extract → peer/competitor extract → **peer frameworks** (the `app/schemas/peer.py` pipeline above — `NichePeerSet` is what it consumes).

### Where things live

- **Schemas: `app/schemas/niche.py`** (landed, +11 tests in `tests/test_niche_schemas.py`). Provenance rule same as peer: scraped/computed = code only; the LLM *names* things (keywords, niche label, geo hypotheses, queries), code *counts, weights, and verifies* them.
  - `NicheConfig` — evidence windows (originals 100 / replies 50 / RTs 50 / quotes 25 / comments 5×20), `MIN_ORIGINALS_FOR_INFERENCE=20`, synthesis input caps (`SYNTH_*` 40/25/20/10/40), `SOURCE_WEIGHTS` (bio 3.0 → comment_on_peer 0.3; RT counts least — amplifying ≠ practising), `RECENCY_HALF_LIFE_DAYS=45`, `ENGAGEMENT_BOOST_CAP=2.0`, `MAX_KEYWORDS=40`, `MAX_QUERIES=12`, geo confidence 0.6 / free-text cap 0.5, peer bands (0.3–5× peer, 5–50× aspirational, above = giant), keep counts 10/5/3, hard-reject thresholds (`MIN_ORIGINAL_RATIO=0.3`, `BOT_SCORE_REJECT=0.7`), `PEER_CACHE_TTL_HOURS=12`, `PEER_COMMENT_MINING=False`.
  - scraped inputs: `ProfileEnrichment` (bio/location/followers/website/pinned post…), `ReplyContext` (+parent + `conversation_id` + `lang`), `RetweetContext` (full original text + author — captions are truncated), `CommentSample` (audience vocabulary/geo; `looks_spam` computed by rules).
  - computed: `DeterministicFeatures` (n-grams by distinctiveness, hashtags/cashtags/mentions, reply/RT/quote targets, commenters, domains, lang mix, 24-bucket UTC hour histogram, currency + gazetteer place hits, `thin_history`).
  - geo model: `GeoProfile` with **three kept-separate scopes** — `creator` (where the person is) / `audience` (where engagers are) / `niche` (is the topic place-bound) → `geo_relevance: local_first | regional | global`; every `GeoSignal` requires ≥1 evidence item; profile free-text location capped at 0.5 confidence; below 0.6 geo is a hint, not a filter.
  - LLM output: `NicheLLMOutput` (label, slug, keywords ≤40 typed + search-worthy, geo, tiered queries ≤12, `missing_evidence`, `needs_user_confirmation`, confidence) — validator enforces **local_first ⇒ ≥1 geo query**; `NicheQuery` carries code-computed `validation_hits`/`weak`.
  - stored results: `ScoredKeyword` (0–1 weight × per-source evidence counts), `PeerSeed` (code-built from the interaction graph — **the LLM never produces handles**), `NicheProfile` (`status: ok|thin_history|failed`, `niche_key = slug:geo_scope`, `user_overrides` always win, **failed/thin_history carry no fabricated niche — ask the user**).
  - peer discovery: `PeerCandidate` (size bands, `geo_match` None-when-unknown, `bot_score`, `niche_fit` 1–5, flags, `status: candidate|vetted|rejected` — LLM failure never auto-promotes), `PeerVettingOutput`, `NichePeerSet` (`giants` stored as reference only, **excluded from baselines/benchmarks**).
- **Planned, not built (Prompt 1):** additive nullable columns on `profiles` (bio/location/followers/…), `posts` (`kind` incl. quote, `conversation_id`, `media_type`, `lang`, `hashtags/mentions/urls`, `quoted_*`, `kind_source='api'|'heuristic'`), `metric_snapshots` (`quotes`, `bookmarks`; `shares` documented as retweets-only), `user_activity` (parent + RT-original + `lang` columns); new tables `post_comments`, `profile_niche`, `niche_keywords`, `niche_registry` (**shared polling is per `niche_key = topic_slug:geo_scope`** — without geo in the key, Nigerian and US fintech share one benchmark pool), `niche_peers`. Then `app/niche/{features,synthesize,postprocess,discover}.py` for Prompts 2–3; hardcoded `DEFAULT_NICHE_QUERY`/`DEFAULT_NICHE_HANDLES` deleted when Prompt 3 wires `niche_peers` into bootstrap/prompts/trends/frontend.

### Key correctness properties

Source weighting (bio strongest, RT weakest) × distinctiveness × recency decay × engagement boost, normalized 0–1; every place/quote the LLM names is verified against the evidence given, anything else dropped + logged; geo from a lone free-text profile location capped at 0.5; user confirmation always wins (one-tap onboarding + re-extraction); thin history (<20 originals) asks the user instead of inferring; comments are sampled (never full-scraped), spam flagged and **never fed to the LLM**; both runtime prompts wrap third-party text as untrusted data (prompt-injection guard — don't edit that line out); credit budget forced before wiring (Prompt 1's Step 0 cost report).

### Audit fixes vs the source schema file

Added `RetweetContext` (RT originals had no model); `ReplyContext.lang`; `CommentSample.sampled_at` and `PeerCandidate.last_verified` (both real table columns in the md); `NicheQuery.validation_hits`/`weak` (Prompt 2's "kept but marked weak" needed a home); named the magic numbers (`SYNTH_*` input caps, `BIO_SNIPPET_CHARS`, `MIN_ORIGINAL_RATIO`, `BOT_SCORE_REJECT`, `PEER_CACHE_TTL_HOURS`, `PEER_COMMENT_MINING`, `VETTING_POSTS_PER_CANDIDATE`); `SOURCE_WEIGHTS` typed `ClassVar`; converted to repo `X | None` style.

### Open items

- **Prompt 1 Step 0 (blocking):** Xpoz capability report — profile lookup, structural post flags (is_reply/is_quote/conversation_id), parent-post fetch, comment fetch (+ commenter profile fields), bookmark/quote counts, search query syntax. Saved to `docs/xpoz_capabilities.md` before any ingestion change.
- Credit cost per user for the full backfill — report before wiring (`XPOZ_RUN_CREDIT_BUDGET` shared with the peer pipeline).
- Language detector choice (Pidgin handling — if unsupported, mark `pcm` unknown, never mislabel); background corpus choice for n-gram distinctiveness; gazetteer list for our user countries.

---

## HTTP Endpoints & Agent Tools

Analysis covers `lumi/app/routers/*.py`, `lumi/app/tools/*.py`, `.agents/api-endpoints.md`, `docs/routers.md`, `docs/tools.md`
(plus the services those files delegate to, where needed to judge completion state).

### 1. REST endpoint inventory

App wiring: `app/main.py:93-101` mounts `chat`, `profiles`, `alerts`, `pfm`, `trends`, `handles`, `voice`, `mcp_google`, `repurpose`; CORS is fully open (`app/main.py:86-91`);
`GET /health` at `app/main.py:104-115`. There is **no auth anywhere** — every route trusts a client-supplied `profile_id`.

| # | Method + path | Handler | Request | Response | In `.agents/api-endpoints.md`? |
|---|---|---|---|---|---|
| 1 | `POST /chat` | `chat.py:44` | `ChatRequest{profile_id, message}` (`chat.py:21`) | `ChatResponse{role, content, tool_calls_made, tool_executions}` (`chat.py:26`) | Yes (`:15`) |
| 2 | `POST /chat/stream` (SSE) | `chat.py:54` | `ChatRequest` | `StreamingResponse`, `text/event-stream` | **No** |
| 3 | `GET /chat/history` | `chat.py:85` | query `profile_id`, `limit=50`, `before` | `ChatHistoryResponse` (`chat.py:40`) | Yes (`:47`) |
| 4 | `DELETE /chat/history` | `chat.py:110` | query `profile_id` | raw `{"status","deleted_count"}` | **No** |
| 5 | `POST /chat/title` | `chat.py:128` | `ChatTitleRequest{message}` (`chat.py:120`) | `ChatTitleResponse{title}` | **No** |
| 6 | `GET /profiles` | `profiles.py:55` | — | `ProfileListResponse` (`profiles.py:25`) | Yes (`:85`) |
| 7 | `POST /profiles/{profile_id}/select` | `profiles.py:85` | path id only | `ProfileSelectResponse` (`profiles.py:29`) | Yes (`:108`) |
| 8 | `GET /profiles/{profile_id}/analytics` | `profiles.py:101` | path id | untyped `dict` | **No** |
| 9 | `GET /profiles/{profile_id}/alerts/unread` | `alerts.py:31` | path id | `AlertsResponse` (`alerts.py:27`) | Yes (`:132`) |
| 10 | `POST /pfm/connect` | `pfm.py:17` | `ConnectRequest{platform, external_id="lumi_user"}` (`pfm.py:12`) | untyped PFM dict (`{"url": ...}`) | **No** |
| 11 | `GET /pfm/callback` | `pfm.py:30` | query `isSuccess`, `accountIds`, `error` | `{"connected", ...}` | **No** (only `docs/routers.md:19-22`) |
| 12 | `GET /trends/matches` | `trends.py:43` | query `profile_id=1`, `limit=50` | `TrendMatchesListResponse` (`trends.py:27`) | **No** |
| 13 | `POST /trends/scan` | `trends.py:75` | `ScanTrendsRequest{profile_id=1, handles=[...], min_likes=20}` (`trends.py:31`) | `ScanTrendsResponse` (`trends.py:37`) | **No** |
| 14 | `GET /handles/search` | `handles.py` `search_handles` (delegates to MVP `api_search`) | query `q`, `context`, `platforms` (CSV, default `x`) | `{query, context, results[{handle, display_name, avatar_url, followers, source, platform}], live, refreshed, reason, platforms, platform_reasons, live_queries_this_session, credits_spent_this_session}` | **Yes** (added 2026-10-21; `platforms` 2026-10-25) |
| 15 | `GET /handles/saved` | `handles.py` `list_saved_handles` (→ MVP `api_saved`) | query `platforms` (CSV, default `x`) | `{results[≤500], count}` | **Yes** (2026-10-21; `platforms` 2026-10-25) |
| 16 | `POST /handles/select` | `handles.py` `select_handle` (→ MVP `api_select`) | `SelectHandle{handle, platform="x", display_name, avatar_url, followers, selected_query}` (MVP pydantic model) | `{"remembered": true, "handle"}` | **Yes** (2026-10-21) |
| 17 | `GET /handles/stats` | `handles.py` `get_handle_stats` (→ MVP `api_stats`) | — | `JSONResponse` passthrough (credit meter, saved counts, TTL) | **Yes** (2026-10-21) |
| 18 | `POST /voice/transcribe` | `voice.py` | audio blob (wav) | transcript dict | **Yes** (line 161) |
| 19 | `GET /health` | `main.py:106` | — | `{"status":"ok", ...latency block from `turn_metrics.recent_turn_latency()`, omitted when empty}` | **No** |
| 20 | `GET /mcp/google/connect` | `mcp_google.py` `connect` | — | `302` to Google consent; or `503 {"error":"google_oauth_not_configured", ...}` when the OAuth client env vars are unset | **Yes** (added 2026-10-21) |
| 21 | `GET /mcp/google/callback` | `mcp_google.py` `callback` | query `code`, `state`, `error` | `{"connected": true, "scopes": [...]}` or `{"connected": false, "error": ...}` | **Yes** (2026-10-21) |
| 22 | `GET /mcp/google/status` | `mcp_google.py` `status` | — | `{"connected", "configured", "scopes", "expires_at", "connect_path"}` — `configured` = OAuth client env vars present | **Yes** (2026-10-21) |
| 23 | `POST /repurpose` | `repurpose.py` `repurpose` (`:77`) | `RecaptionRequest{source_text (1-8000), platforms[1-8], profile_id?, must_keep_phrases[≤20]}` (`repurpose.py:54`) | `RecaptionResponse{profile_id, results[], elapsed_ms}`; each result `{platform, rule_platform, ok, attempt_id, request_id, output, changes, must_keep_passed, judge_verdict, judge_confidence, route_label, fallback, error}` | **Yes** (added 2026-10-25) |

**9 of 23 routes are absent from `.agents/api-endpoints.md`** (the four `/handles/*` + three `/mcp/google/*` routes were documented 2026-10-21 and `POST /repurpose` 2026-10-25, so the spec now covers 14).
Every one except `/health` is consumed by the shipped frontend
(`frontend/src/api/client.ts`: stream, delete history, title, pfm/connect, trends/matches,
trends/scan, analytics, voice transcribe, and the three handle-search calls `searchHandles` / `getSavedHandles` / `selectHandle` in `PromptBar.tsx`), so the spec — not the code — is the thing that drifted.

Per-endpoint notes / quirks:

- **`POST /chat`** (`chat.py:44-51`) is a one-line pass-through to `run_agent_loop` (`app/agent/loop.py:80`). `role` is always
  the literal `"assistant"` (`chat.py:27`). Tool exceptions are **not** caught here (`loop.py:139`) → bare 500 with no JSON body,
  which `docs/frontend-integration.md:41,119` documents as expected behaviour rather than a bug.
- **`POST /chat/stream`** (`chat.py:54-80`): builds an `asyncio.Queue`, spawns `runner()` via `asyncio.create_task(runner())`
  (`chat.py:70`) and immediately returns a `StreamingResponse`. Events are bare `data: {json}\n\n` frames with no `event:`/`id:`
  fields (`chat.py:78`), types `tool_start` / `tool_done` (from `loop.py:131-137,163-171`), `done` (`chat.py:64`), `error`
  (`chat.py:66`), terminated by a `None` sentinel (`chat.py:68,76`). The `done` event carries `content` + `tool_executions`
  but **not** `tool_calls_made`, so the SSE contract differs from `POST /chat`.
- **`GET /chat/history`** excludes `ChatRole.TOOL` rows (`chat.py:92`), orders `id desc`, then re-sorts ascending before
  returning (`chat.py:101`). `limit` is an unvalidated bare int (`chat.py:87`) — no `Query(le=...)` bound. The `before` filter is
  applied *after* `.limit()` in code order (`chat.py:94-97`); harmless because SQLAlchemy composes the WHERE at compile time, but
  it reads like a bug.
- **`DELETE /chat/history`** (`chat.py:110-117`) takes `profile_id` as a **query** param, loads every row, then issues one
  `session.delete()` per row + commit — N round-trips instead of a single `DELETE ... WHERE profile_id = ?`. No `response_model`.
- **`POST /chat/title`** (`chat.py:128-151`) lazily imports the provider, interpolates the raw user message into the prompt
  (`chat.py:134`), strips quotes/markdown, and falls back to the first 4 title-cased words if the LLM output is empty or >35
  chars (`chat.py:144-151`). All exceptions swallowed → always 200.
- **`GET /profiles`** (`profiles.py:55-80`) does **not** list all profiles: it filters to `USER_HANDLES` / `USER_PFM_IDS`
  (`profiles.py:51-52,59-66`) and force-sorts `@AtehOfficial` first (`profiles.py:66`). `_has_voice_profile` counts *any*
  voice-profile version, not the current one (`profiles.py:38`).
- **`POST /profiles/{id}/select`** (`profiles.py:85-98`) is a stateless state snapshot — nothing is mutated. `.agents/api-endpoints.md:110`
  wrongly says it "sets the active profile for the session" and "clears chat context"; `docs/routers.md:13` has it right.
- **`GET /profiles/{id}/analytics`** (`profiles.py:101-108`) returns an untyped dict and **has side effects**: it delegates to
  `services.analytics.get_profile_analytics` (`analytics.py:141`), which ingests (PFM feed, Xpoz fallback) and `session.commit()`s on a GET.
  Raises 404 only when the service returns an `"error"` key. `GET /profiles` now also serializes `timezone`/`timezone_source`
  on each profile (currently null until inference runs or the user confirms).
- **`GET /profiles/{id}/alerts/unread`** (`alerts.py:31-61`) shares the `/profiles` prefix with `profiles.py` (two routers, one
  prefix, different tags — no route collision today). Velocity is recomputed live from all snapshots per post, so the number is
  not the one that triggered the alert (documented at `docs/routers.md:17`).
- **`POST /pfm/connect`** (`pfm.py:17-27`) hardcodes `permissions = ["read","write"]` (`pfm.py:23`) — different from the
  `connect_account` tool's `["posts","feeds"]` (§5). Returns PFM's raw JSON, untyped.
- **`GET /pfm/callback`** (`pfm.py:30-69`) returns **JSON to the user's browser** — no redirect back into the SPA. Known gap,
  called out at `pfm.py:38-40` (redirect URL must be registered manually in the PFM dashboard) and `docs/frontend-integration.md:108`.
- **`GET /trends/matches`** (`trends.py:43-72`) defaults `profile_id=1` (`trends.py:45`) — hard profile assumption. Returns
  `m.id or 0` (`trends.py:60`), masking a `None` primary key instead of failing.
- **`POST /trends/scan`** (`trends.py:75-86`) directly calls the agent tool `check_niche_trends` (imported at `trends.py:10`) —
  a router calling tool code, bypassing the registry. Its defaults (`profile_id=1`, `min_likes=20`, five hardcoded handles at
  `trends.py:32-34`) disagree with the tool's own schema (`min_likes` documented as "default: 50", `listening.py:113,122`).

### 2. Tool registry mechanism

- `ToolSpec` dataclass + module-level `_REGISTRY: dict[str, ToolSpec]` (`registry.py:8-16`).
- `@tool(name, description, parameters)` (`registry.py:19-26`) is a pure **import-time** side effect: it inserts into
  `_REGISTRY` keyed by name (silent overwrite on duplicate — no uniqueness check) and returns the function unchanged.
- `parameters` is a hand-written OpenAI-style JSON Schema dict per tool — **no introspection of type hints**, so schema and
  signature can (and do) drift; `required` is simply omitted where nothing is required (e.g. `connect_account`, `connect.py:17-25`).
- `list_tool_specs()` (`registry.py:33-45`) emits `{"type":"function","function":{name, description, parameters}}` for every
  registered tool **and appends the cached MCP connector specs** (`mcp__<connector>__<tool>`, from `services/mcp.py:list_specs()`
  — best-effort, never raises); `agent/loop.py` sends **all native tools + every authenticated connector's tools on every
  completion call** — no per-profile gating. With no connector authenticated the merged set is empty and nothing changes.
- `call_tool(name, arguments)` (`registry.py:48-52`) dispatches with `await spec.func(**arguments)`: unknown name → `ValueError`,
  wrong/missing/extra keys → raw `TypeError` bubbling up. **Names starting with `mcp__` route to `services/mcp.py:call_tool`**
  (discovery-split, token refresh, `tools/call` over Streamable HTTP, 60s per-call timeout, honest `{error}` payloads — never a
  raised 500). **There is no argument validation against the JSON schema anywhere**;
  the LLM's `arguments` string is `json.loads`-ed unguarded at `loop.py:127`.
- Side-effect import: `app/tools/__init__.py:3` — `from app.tools import actions, activity, advice, analytics, backfill, connect, listening, memory, posts, repurpose, voice`.
  Any module missing from that line silently never registers. `registry` itself is not in `__all__` (`__init__.py:5`) but is still
  importable as a submodule. `agent/loop.py:11` (`from app.tools import registry`) transitively triggers the whole package import,
  so registration happens as long as the loop is imported. `background/poller.py:8` imports `app.tools.listening` directly (same
  transitively-triggered init).
- `docs/tools.md:10` shows the import list **without `analytics`** — the doc snippet is already stale vs `tools/__init__.py:3`.
- Tests: `tests/test_registry.py` covers decorator registration, spec shape, dispatch, unknown-tool error (4 tests).

### 3. Registered tools (20 native + dynamic MCP tools)

Registration order follows `tools/__init__.py`: actions → activity → advice → analytics → backfill → connect → listening → memory → posts → repurpose → user_requests → voice. MCP connector tools are **not** in this registry — they're discovered per-turn and merged at spec-listing time (see §2 above and the MCP Connectors section below).

| Tool | File:line | Parameters (schema) | Real / stub |
|---|---|---|---|
| `submit_action` | `actions.py:7` | `attempt_id`, `action` (enum accept/edit/reject), `edited_text?` | Real, under-validated |
| `dismiss_alert` | `actions.py:34` | `post_id` | Real |
| `get_user_activity` | `activity.py:8` | `profile_id`, `kind?="all"` (reply/retweet/all), `limit?=15` | Real; replies are the user's own words, retweets never attributed |
| `get_peer_advice` | `advice.py:70` | `profile_id`, `query` | Real; Chroma-first retrieval, Xpoz+LLM scan fallback stores what it finds; every `store`/`live_extraction` hit now carries provenance for prompt rule 18: top-level `niche_title`, `source_handles` (union of DB `payload.top_peer_handles` + post authors), `age_days` (oldest `peer_frameworks.created_at`, `None` when unknown — never a fake number) via `_store_provenance` |
| `get_analytics` | `analytics.py:5` | `profile_id` (required) | Real; **fabricated fallback removed** — NULL-safe, ingest + display (see below) |
| `backfill_posts` | `backfill.py:7` | `profile_id` | Real; deep paginated PFM backfill via shared ingest (`services/pfm.py:87`) |
| `connect_account` | `connect.py:9` | `handle?` (no `required`) | Real + **hardcoded shortcut** |
| `start_listening` | `listening.py:24` | `profile_id`, `interval_minutes?=5` | Real (flag flip) |
| `stop_listening` | `listening.py:50` | `profile_id` | Real (flag flip) |
| `check_trending` | `listening.py:68` | `profile_id` | Real; velocity (floor × own-baseline) + Jev backstop (see below) |
| `check_niche_trends` | `listening.py:228` | `profile_id`, `handles`, `min_likes?=50` | Real (Xpoz); coerces `min_likes` to `int` at entry (the model can send `"50"` — the registry does no type coercion; live `int < str` crash 2026-10-21, pinned by `tests/test_xpoz_resilience.py`); result now includes `scanned_handles` (handle → posts fetched, read by the loop's coverage gate, §5 5f) alongside `failed_handles`; also persists every user it touches to the shared handle DB (`origin: niche`) |
| `discover_and_extract_niche_frameworks` | `listening.py:387` | `profile_id`, `query` | Runs the peer pipeline (`app/services/peer_pipeline.py`): keyword search discovers the accounts, per-account baseline-relative winners, blind tagging, lift-grounded report; persists `niche_framework_reports` + `post_taggings` and bridges to `peer_frameworks`/Chroma; persists search-result authors to the handle DB (`min_impressions` removed 2026-10-26 — winners are judged against each account's own median, not an absolute filter) |
| `get_posts` | `posts.py:8` | `profile_id`, `limit?=20` | Real |
| `remember` | `memory.py:7` | `profile_id`, `memory`, `kind?="fact"` | Real (Chroma `profile_bullets` + rolling memory.md) |
| `recall_memory` | `memory.py:39` | `profile_id`, `query`, `limit?=5` | Real (Chroma semantic search) |
| `repurpose_caption` | `repurpose.py:47` | `profile_id`, `platform?="x"`, `post_id?`, `source_text?`, `must_keep_phrases?` | Real LLM + enforce + judge |
| `extract_voice_profile` | `voice.py:35` | `profile_id` | Real LLM + shared-policy backfill |
| `get_voice_profile` | `voice.py:140` | `profile_id` | Real |
| `answer_style_questions` | `voice.py:170` | `profile_id`, `answers[]` | Real (plain inserts) |
| `save_user_request` | `user_requests.py` | `profile_id`, `handles[]`, `request?` | Real; records pasted handles as USER REQUESTS in `user_search_requests` (never the peer stores), normalizes/validates handles, reports `already_requested` + `in_peer_set` membership (sources: niche defaults, `peer_frameworks` payloads, `listening_matches` authors); 0 credits, no search inside — the agent searches via `check_niche_trends` afterwards |

**`connect_account`** (`connect.py:27-54`) — hardcoded PFM account `spc_U8xOuoxKCYpKAbzUymPCd` is fetched at `connect.py:34`;
if the handle is empty **or** equals `atehofficial` (`connect.py:32`) and that account reports `status == "connected"`, the tool
short-circuits with `already_connected: True, handle: "AtehOfficial"` (`connect.py:36-41`) — i.e. a second user with no handle
would be told *their* account is Ateh's. Otherwise it calls `auth-url` with `external_id = handle or "ateh_x_connect"`
(`connect.py:46`) and permissions `["posts","feeds"]` (`connect.py:47`), and falls back to `handle: "AtehOfficial"` in the
response (`connect.py:51`). It never touches the DB (matches `docs/tools.md:17`).

**`extract_voice_profile`** (`voice.py:47+`) — filters local posts to `is_authentic_original` and, when the count is `< 5` (`MIN_POSTS_FOR_EXTRACTION`), calls `_attempt_pfm_backfill` (`voice.py:21-45`), which now **delegates to `services.pfm.backfill_profile_posts`** (the shared deep-ingest path: classification, truncation flag, snapshot policy, deletion suspects, timezone, profile snapshots) rather than its own single-page fetch. Errors are swallowed to `logger.debug` like before; a missing/empty `pfm_account_id` is refused with a debug log. Version handling is correct per the partial unique index: current row is flipped to `is_current=False` + flushed first, then `max(version)+1` is computed and a new current row inserted. Example posts come from a diverse Chroma corpus sample (not `posts[:10]`), and reply samples from `user_activity` feed `reply_style` only.

**`repurpose_caption`** (`tools/repurpose.py:34+`) — resolves `post_id` → caption or uses `source_text`, normalizes
`must_keep_phrases` (a JSON-string array from the model is parsed, `tools/repurpose.py:10-31`), loads the current voice profile
in one read session, then runs the **shared DB-free pipeline** `run_platform_repurpose()` (`app/services/repurpose_flow.py` —
see §6b) and only **after it returns** commits the `RepurposeRequest` plus one `RepurposeAttempt` per attempt. An LLM failure
therefore leaves **no orphan request row** (the pre-2026-10-25 "commits before generation" bug), attempts now carry the real
`platform`/`tier`/`model`/`provider`/`attempt_no` from the flow, and `enforce()` receives `platform_char_limit(platform)`
instead of a hardcoded 280 — both previously-documented problems (attempt platform always `x`, non-X rewrites failing
`must_keep` by construction) are fixed. It also flips `alert_dismissed` when the source post came from an alert. Remaining
quirks: a bare `assert attempt is not None` would turn a zero-attempt outcome into a 500, and a generator passthrough is only
inferable from `changes[].reason == "Fallback mode"` — the REST endpoint surfaces it as `fallback: true`, the tool does not.

**`check_trending`** (`listening.py:68-145`) — no more module-level `SPIKE_THRESHOLD_LIKES_PER_HOUR`. Per profile it loads all posts, queries `MetricSnapshot` **per post** (N+1, `listening.py:81-83`), and calls `detect_spike(snapshots)` (`services/metrics.py:33+`), which now enforces a **floor (`SPIKE_FLOOR_LIKES_PER_HOUR = 5.0`) times a multiplier (`SPIKE_MULTIPLIER = 3.0`) over the post's own baseline** velocity (`current_and_baseline_velocity`, `metrics.py:13-26`). When velocity can't decide (< 2 snapshots) a **Jev backstop** fires for never-alerted posts with ≥ 50 absolute likes (`SPIKE_JEV_LIKE_FLOOR = 50`, capped at `SPIKE_JEV_MAX_JUDGMENTS = 3` per run, `listening.py:15-19,92-118`) — a bounded, credit-aware absolute-likes escape hatch, not the old threshold. Alert-once logic is unchanged: skip if `alerted_at is not None and not alert_dismissed`; on alert set `alerted_at=now` **and reset `alert_dismissed=False`**; commit **inside the loop** (one transaction per alerted post, so a mid-loop exception leaves earlier alerts committed); a second commit updates `poll_config.last_polled_at`. The poller discards `newly_alerted_post_ids` (`poller.py:44-46`). Snapshot accumulation now happens via the shared ingest policy on analytics GETs and `backfill_posts` runs, so ≥ 2 snapshots per post do accumulate over time — and since 2026-10-25 the poller *also* fetches on its own tick (`backfill_profile_posts`, `poller.py:36-43`, non-`demo-` `pfm_account_id` only), so alerts no longer depend on an inbound request when PFM is available.

**`check_niche_trends`** (`listening.py:146-264`) — real Xpoz integration writing to `listening_matches` via `XpozClient`
(`services/xpoz.py:31-49`): per handle `get_user_live_posts(limit=10)`, filter `like_count >= min_likes`, de-dupe on
`(profile_id, platform_post_id)`, build `ListeningMatch`, one `commit()` after the whole double loop. Per-handle fetch
failures are logged and skipped. **Also feeds the shared handle DB** (`services/handle_db.py`): every tracked account goes
through `remember_scanned` (bounded enrichment — picture/name/followers for genuinely-new handles, exact username match
only) and every author of every returned post — viral or not — through `remember` (handle-only), both `origin: niche`;
the block is exception-shielded so a handle-DB failure never fails the scan. Quirks: `import logging` + `logger` created
*inside* the function; the tool schema says `min_likes` "Default: 50" while the HTTP wrapper passes 20 (`trends.py:34`).
This directly contradicts `CLAUDE.md`'s claim that "`listening_matches` … nothing writes to it yet — no `XpozClient`, no
tool".

**`discover_and_extract_niche_frameworks`** (`listening.py:359-474`) — `XpozClient.search_live_posts(query, limit=25)` (retried once on 5xx/network),
**persists every search-result author to the handle DB first** (`services/handle_db.py`, `remember`, `origin: niche`,
`query` recorded — handle-only by design: keyword searches surface unbounded authors and enrichment stays capped to
scanned accounts; saved even if a later step fails, because the search happened and the users were seen), then takes the
distinct authors as handles and runs `run_peer_pipeline` on them (per-account fetch → 28-day baseline → 1.5×-own-median
winners → blind tagging → lift → synthesis). The report is bridged through `legacy_payload_from_report` into a
`peer_frameworks` row + Chroma (`peer_frameworks`, `peer_posts` winners) so `get_peer_advice` keeps serving from the
store, and the full JSON report is persisted to `niche_framework_reports`/`post_taggings`. Result adds `report_status`,
`report_id`, `scanned_handles` and `fetch_failures` (a partial fetch is a footnote). On search failure: honest `error`
payload, no pipeline run, no DB/Chroma write. `min_impressions` is gone — there is no absolute impression filter any more.

**`get_analytics`** (`analytics.py:5-…`) → `services.analytics.get_profile_analytics` (`analytics.py:141-282`). Ingest: zero posts → `_ingest_pfm_feed` (`analytics.py:36`); still empty → `_ingest_xpoz_user_posts` (`analytics.py:84`) via the profile handle — the working alternative while the PFM feed endpoint 401s. Both go through the shared policy in `app/services/ingest.py`, so classification, truncation, deletion-suspect, snapshot-policy, timezone, and profile-snapshot behavior are identical by construction with `backfill_posts`. Display is **NULL-safe**: sums use `or 0` for display only (`analytics.py:185-188`) — a missing metric is unknown, never a fabricated 0 in storage. The old fabricated demo branch (28450 impressions / 14.8% / TXT 52.4% / invented top posts) is **gone**; the no-data path (`analytics.py:192-213`) returns zeros plus an honest summary with `is_live_data: False`. Live mode pairs posts with snapshots **by `post_id`** (`analytics.py:216-225` — the old positional `zip` misalignment is fixed), computes real allocation percentages (the `or 40.0`/`or 35.0` fabrication is removed), builds the trend series as normalized deltas from real snapshots only, and ranks `top_posts` by real views. Side effect on GET remains by design: the route ingests and commits (incremental, ≤ `INCREMENTAL_REFRESH_LIMIT = 20` items per pass).

**`get_posts`** (`posts.py:20-33`) — `ORDER BY published_at DESC LIMIT n`, returns `{id, caption, published_at}` only; no cursor
pagination (acknowledged at `docs/tools.md:22`).

**`submit_action` / `dismiss_alert`** (`actions.py:20-31,39-49`) — `submit_action` does not enforce its own schema note that
`edited_text` is "Required when action is 'edit'" (`actions.py:15`), and `UserActionType(action)` raises `ValueError` → 500 on an
invalid enum (`actions.py:26`). `dismiss_alert` flips `alert_dismissed` only, leaving `alerted_at` set (`actions.py:45`) — matches
the alert-once-per-episode design in `docs/tools.md:21`.

**`start_listening` / `stop_listening`** (`listening.py:27-56`) — upsert/toggle `PollConfig.is_active` + `interval_minutes`;
`stop` on a missing config returns `{"listening": False}` without error (`listening.py:49-50`). Consumed by the lifespan poller
(`main.py:66`, `poller.py:23-52`, `TICK_SECONDS = 120`).

**`get_voice_profile` / `answer_style_questions`** (`voice.py:158-176,201-209`) — current-version read; batch insert of style
answers with no versioning (as noted at `docs/tools.md:18`).

### 4. Hardcoded values & single-user assumptions

- `routers/profiles.py:51-52` — `USER_HANDLES = {"atehofficial","ateh","just_ateh"}`,
  `USER_PFM_IDS = {"spc_U8xOuoxKCYpKAbzUymPCd","spc_VoWGXwlzvgGx9el6AtN1"}`; used to hide every other profile from `GET /profiles`
  (`profiles.py:59-66`) and to pin `@AtehOfficial` first (`profiles.py:66`).
- `seed.py:11-12` — a *different* `USER_HANDLES`/`USER_PFM_IDS` pair (mixed case, one PFM id) that is **never referenced anywhere**
  (dead constants). The seed itself hardcodes `spc_U8xOuoxKCYpKAbzUymPCd` four times (`seed.py:22,34,47,54`) and forces
  `handle="AtehOfficial"`, `name="Ateh Ugoji"` on the existing row (`seed.py:51-54`) — it overwrites whatever the OAuth callback
  wrote. Its docstring promises "purging all third-party accounts" (`seed.py:16`) but no purge exists.
- `tools/connect.py:34,46,51` — hardcoded account id, `"ateh_x_connect"` default external id, `"AtehOfficial"` fallback handle.
- `routers/pfm.py:14` — `external_id: str = "lumi_user"` default: every frontend-initiated connect shares one external id.
- `routers/trends.py:32-34` — `profile_id: int = 1` and default handles `["sama","levelsio","karpathy","paulg","swyx"]`
  (mirrored client-side at `frontend/src/api/client.ts:201`); `trends.py:45` repeats `profile_id: int = Query(1)`.
- `agent/prompts.py:7-10` — system-prompt rule 2 bakes in the product decision: if `connect_account` reports already-connected,
  "confirm that `@AtehOfficial` is already connected". Rule 4 hardcodes `['sama','levelsio','paulg','karpathy']`
  (`prompts.py:13-14`); rule 5 says "if no voice profile, call `connect_account` first" (`prompts.py:15`), which cannot create a
  voice profile — wrong tool.
- ~~`services/frameworks.py:126-154` — canned framework fallback~~ **deleted 2026-10-26** with Prompt 3 (the analytics fabricated-data path was removed earlier); no fabricated-analysis path remains.
- `routers/profiles.py:13` — `PLATFORM = "x"` constant; `main.py:31` — `allow_origins=["*"]`.

### 5. OAuth connect flow as implemented

1. **Agent path**: `connect_account` → PFM `POST /v1/social-accounts/auth-url` with
   `platform="x"`, `external_id=handle or "ateh_x_connect"`, `permissions=["posts","feeds"]` (`connect.py:46-47`,
   `services/pfm.py:26-33`) → returns `{"connect_url": url}` → the system prompt mandates presenting it as
   `[Connect X](<url>)` on its own line (`prompts.py:9-10`).
2. **Frontend path (parallel, undocumented)**: `POST /pfm/connect` → same endpoint but `permissions=["read","write"]` and
   `external_id="lumi_user"` (`pfm.py:23-24`) → returns PFM's raw `{"url": ...}`.
3. **User authorizes on X**; PFM redirects the browser to `GET /pfm/callback?isSuccess=...&accountIds=...&error=...`
   (`pfm.py:31-35`).
4. **Profile creation**: `pfm_callback` loops comma-separated `account_ids`, calls `get_social_account(id)` per account
   (`pfm.py:48-49`), upserts `Profile` by `pfm_account_id` (`pfm.py:53-62`), commits **per account** (`pfm.py:63`), and returns
   `{"connected": true, "profiles": [{profile_id, handle}]}`. This is the only place a `Profile` row is created
   (consistent with `docs/routers.md:21`, `docs/tools.md:17`).
5. **Failure branch**: non-`"true"` `isSuccess` or empty `accountIds` → `{"connected": false, "error": ...}` with HTTP 200
   (`pfm.py:41-42`).

**Gaps**
- The redirect URL must be registered manually in the PFM dashboard; it cannot be set per-request with PFM's system credentials
  (`pfm.py:36-40`) — nothing in the repo records what that URL is.
- The callback returns raw JSON in the browser: the user lands on a blank JSON page instead of back in the SPA
  (`docs/frontend-integration.md:108` explicitly flags this as undecided).
- `isSuccess`/`accountIds` are required query params (`pfm.py:32-33`, `Query(...)`) → PFM omitting either yields a FastAPI 422,
  not a friendly error page.
- Two entry points produce divergent `permissions`/`external_id`; only the callback path writes the DB, so a `POST /pfm/connect`
  URL opened by the user lands on the same callback — fine — but there is no way to know which entry point started the flow.
- No verification that `account_id`s returned actually belong to the caller (there are no callers/users to verify against).

### 6. Bugs / quirks

**SSE lifecycle (`chat.py:54-80`)**
- `asyncio.create_task(runner())` at `chat.py:70` stores no reference — CPython may garbage-collect the task mid-flight (the
  documented pitfall); no handle for cancellation either.
- On client disconnect the generator is torn down but `runner()` keeps running the full agent loop, continuing to write chat rows
  to the DB after the viewer is gone; nothing cancels it, and if the loop hangs the client waits forever (no timeout, no
  `:ping` keepalive, no `retry:` hint, no `Cache-Control`/`X-Accel-Buffering` headers).
- Errors arrive as a normal `error` event under HTTP 200 (`chat.py:66`), so status-based error handling in
  `client.ts:66` never fires for agent failures — the SSE `error` payload is now surfaced as an `⚠️` reply in
  `App.tsx` (was: silently dropped → misleading "I finished working on that…" success text).
- No `response_model`/OpenAPI schema for the stream.

**Session / commit patterns**
- `session_scope` (`database.py:33-37`) only opens/closes — every caller must commit manually; several commit mid-loop:
  `listening.py:84,91` (per-post), `routers/pfm.py:63` (per-account), `services/pfm.py:143` (per backfill page), `services/analytics.py` (per ingest pass).
- `repurpose_caption` commits the request before doing work (`repurpose.py:54`) → orphaned `repurpose_requests` on failure.
- `extract_voice_profile` flip-then-insert relies on flush ordering (`voice.py:120-138`) with no transaction guard against
  concurrent extraction (duplicate `version` → 500).
- No rollback explicitly on error anywhere (relies on session close); partially-committed work in the loops above is not undone.

**N+1 queries**
- `alerts.py:44-49`: one `MetricSnapshot` query per alerted post (plus the alert query itself).
- `profiles.py:74-75`: `_has_voice_profile` + `_is_listening` executed per profile (2N+1 over `GET /profiles`); `_post_count`
  adds a third on `/select` (`profiles.py:96`).
- `listening.py:71-73`: one snapshot query per post inside `check_trending`, run by the poller every tick per profile.
- `chat.py:113-115`: row-by-row delete.
- All acknowledged as "fine at 3-profile MVP scale" in `docs/routers.md:12` — but `GET /profiles` now filters a growing table.

**Response-model / typing omissions**
- No `response_model`: `POST /chat/stream`, `DELETE /chat/history`, `GET /profiles/{id}/analytics`, `POST /pfm/connect`,
  `GET /pfm/callback`, `GET /health` → untyped `dict` in OpenAPI.
- `ChatResponse.tool_executions: list[dict] = []` (`chat.py:30`) is an untyped catch-all; the SSE `done` event drops
  `tool_calls_made` entirely (`chat.py:64`) — two different response shapes for the same operation.
- `trends.py:60` `m.id or 0` hides `None` ids.

**Encoding / text artifacts**
- Sources are CRLF throughout; the only non-ASCII in the slice are U+2014 em dashes in comments/docstrings
  (`agent/loop.py:178`, `agent/prompts.py:5,18`, `background/poller.py:13`, `models/listening.py:11`, `routers/pfm.py:38`,
  `services/pfm.py:3`) and one emoji inside the voice-extraction prompt (`services/voice.py:56`). No U+FFFD/mojibake in `.py`
  (only in compiled `__pycache__/*.pyc`).
- Markdown-fence stripping is done with `raw.strip("`")` + `cleaned[4:]` in three places (`services/voice.py:175-178`,
  `services/repurpose.py:144-147`) — breaks on ```` ```JSON ````, on fences with a language tag
  of other length, and on any trailing backtick inside the JSON payload.
- Cosmetic: runs of 3 blank lines left in `chat.py:82-84`, `profiles.py:82-84`, `tools/voice.py:39-47`. `uv run ruff check
  app/routers app/tools` → "All checks passed", so lint does not catch these.

**Other**
- `POST /trends/scan` imports a tool function directly (`trends.py:10`) instead of going through `registry.call_tool` — the
  registry is bypassed, so the tool's own schema/defaults are not enforced.
- `call_tool`/`loop.py:127` have no error handling → any tool exception or malformed JSON `arguments` 500s `POST /chat`.
- `GET /profiles/{id}/analytics` mutates state (PFM backfill + commit) on a GET.

### 7. Divergences from `.agents/api-endpoints.md`

1. **9 undocumented routes** (table in §1): `POST /chat/stream`, `DELETE /chat/history`, `POST /chat/title`,
   `POST /pfm/connect`, `GET /pfm/callback`, `GET /profiles/{id}/analytics`, `GET /trends/matches`, `POST /trends/scan`,
   `GET /health`. The spec's "The endpoints below are the minimal surface" (`api-endpoints.md:9`) and
   `docs/frontend-integration.md:23` ("The five endpoints") both understate a 23-route surface; the shipped frontend already
   calls 7 of the 9.
2. **Example response tool names don't exist** — `api-endpoints.md:34` shows `classify_difficulty`, `generate_caption`,
   `check_must_keep`, `judge_intact`; the registry (`§3`) contains none of them.
3. **`GET /profiles` semantics** — spec says "List all seeded demo profiles" (`api-endpoints.md:87`) with a `"platform":
   "instagram"` example (`:97`); implementation hard-filters to one user's handles/PFM ids and is X-only (`profiles.py:13,51-66`).
4. **`POST /profiles/{id}/select`** — spec says it "Set[s] the active profile for the session. Clears or switches the chat
   context" (`:110`); implementation is a no-op snapshot (`profiles.py:85-98`).
5. **Scope statement vs repurpose tool** — `:5,174` say multi-platform repurposing is out of scope and "`platform` … always `x`";
   `repurpose_caption` accepts `linkedin|tiktok|instagram` with full per-platform rule sets (`repurpose.py:15,25`;
   `services/repurpose.py:16-48`). The "always x" claim is now simply false: `app/services/repurpose_flow.py` writes the real `platform` (plus `tier`/`model`/`provider`) onto every `RepurposeAttempt`, and `POST /repurpose` accepts nine frontend platform ids through `PLATFORM_ALIASES`.
6. **"What is NOT an endpoint" list** (`:161-172`) misfiles backfilling under `connect_account`; actual backfill lives inside
   `extract_voice_profile` (`tools/voice.py:20-78`) and `get_profile_analytics` (`services/analytics.py:30-67`), and omits
   `check_niche_trends`, `discover_and_extract_niche_frameworks`, `get_analytics`, `get_posts`, `get_voice_profile`,
   `answer_style_questions`, `dismiss_alert`.
7. **`POST /chat` notes** (`:40`) claim all messages are persisted — true — but omit `tool_executions`, which the code returns
   (`chat.py:29`) and the frontend types (`client.ts:20`).
8. **Spec file itself never mentions SSE/streaming, titles, trends, analytics, or `/pfm/*`**, while CLAUDE.md claims
   `listening_matches` has no writer and lists routers as `chat`/`profiles`/`alerts` — both are contradicted by `app/routers/trends.py`,
   `app/tools/listening.py:124-189`, and `app/services/xpoz.py`.
9. **Stale sibling docs** (re-verified 2026-10-26): `docs/routers.md:3` says "eight files" (there are nine — `app/routers/repurpose.py` / `POST /repurpose` is undocumented there); `docs/tools.md:10`'s import list and "20 tools currently" are now right, but its `check_trending` note still calls spike detection "inert in practice" and its `repurpose_caption` note still claims a 280-char enforce limit, `route_label` never set, and the attempt platform keeping its default (all three fixed by `app/services/repurpose_flow.py`); `docs/services.md:14` still says `backfill_profile_posts` *skips* replies/RTs (they are now routed to `user_activity` by `app/services/ingest.py`); `docs/background.md:7,26` still runs `_bootstrap_pass()` "every poller tick" (removed from the tick in 2026-10). `CLAUDE.md` also instructs that specs are source of truth "…and update them in the
   same change if you deliberately diverge" — the endpoints in §1 were added without that update.
---

## Services, External Integrations & Tests

Analysis of the `lumi/app/services/` layer, the pytest suite, and the planning specs in
`lumi/.agents/external-services.md` + `lumi/.agents/setup.md`. All file:line references are
against the working tree in `C:\Users\USER\Downloads\Lumi-agent-backend\lumi`.

---

### 1. PFMClient (`app/services/pfm.py`)

Thin `httpx.AsyncClient` wrapper around the Post for Me API (`https://api.postforme.dev`,
`pfm.py:11`).

**Implemented endpoints (3 of the ~6 spec'd):**

| Method | Endpoint | Notes |
|---|---|---|
| `create_auth_url` (`pfm.py:26-33`) | `POST /v1/social-accounts/auth-url` | Body `{platform, external_id, permissions}`; returns `{url, platform}` |
| `get_social_account` (`pfm.py:35-38`) | `GET /v1/social-accounts/{id}` | Used by OAuth callback, seed, and `connect_account` |
| `get_account_feed` (`pfm.py:40-47`) | `GET /v1/social-account-feeds/{id}` | Cursor-paginated (`limit`, `cursor` params); each item carries both `caption` and `metrics` per spec line 22 |

**Auth:** app-level JWT bearer header built at construction time — `Authorization: Bearer {settings.pfm_jwt_token}` (`pfm.py:19`), matching the spec (external-services.md:9). 10s read / 5s connect timeout. No client-side rps limiter or retry/backoff; the deep backfill handles 429s itself (below).

**Callers:**
- `backfill_profile_posts` (`services/pfm.py:87`) — the **shared deep-ingest path**: called by the `backfill_posts` tool (`tools/backfill.py`), `tools/voice.py:28` (`_attempt_pfm_backfill`), and bootstrap. Paginates via `get_account_feed` cursor (≤ `MAX_BACKFILL_PAGES = 50`), routes each item through `app.services.ingest` (classification, truncation, deletion suspects, snapshot policy, timezone, profile snapshots), and commits **per page**.
- `app/services/analytics.py:36` (`_ingest_pfm_feed`) — single-page incremental refresh (≤ `INCREMENTAL_REFRESH_LIMIT = 20` items) through the same shared ingest helpers.
- `app/tools/connect.py:34` and `app/seed.py:22` — `get_social_account` with a **hardcoded account id** `spc_U8xOuoxKCYpKAbzUymPCd` (demo-account leakage into library code; `connect.py:32` even special-cases the literal handle `"atehofficial"`).
- `app/routers/pfm.py:24,49` — connect URL + OAuth callback.

**Spec'd but unimplemented / drift:**
- `force_reauth` body field (spec:17) — `create_auth_url` has no such param.
- `GET /v1/social-accounts` list endpoint (spec:20) and `POST /{id}/disconnect` (spec:21) — no methods.
- `/v1/social-posts` publish endpoints (spec:23) — spec says "not yet needed"; correctly absent.
- **Permissions drift:** `routers/pfm.py:23` requests `["read", "write"]`, but the spec is explicit that **`feeds` must be requested or post history/metrics are never accessible** (spec:17). The agent-tool path does it right (`tools/connect.py:47` uses `["posts","feeds"]`), but the REST `/pfm/connect` path is wrong.
- **Cursor pagination now used by the deep backfill** (`services/pfm.py:87`, ≤50 pages / 100 originals via `NicheConfig.ORIGINALS_WINDOW`); the single-page incremental analytics refresh deliberately takes one page.
- **Envelope handling unified**: one `data.get("data") or data.get("items") or []` in `backfill_profile_posts` (`pfm.py:121`) — the old per-caller guessing (`feed.get("data", feed)` vs `data.get("data")`) is gone.
- **Backfill asymmetry resolved**: PFM and Xpoz ingest paths share `store_raw_item`, so RT/reply skipping, dedupe, truncation flags, and snapshot writes are identical by construction.
- **429 partially handled**: `backfill_profile_posts` catches 429, logs a warning, sets `rate_limited`, stops the pass cleanly, and keeps per-page progress (`pfm.py:152-154`). Still no client-side rps limiter or retry/backoff.
- **Doc drift:** `CLAUDE.md` claims "nothing calls `get_account_feed()` yet" — stale; the deep backfill, incremental refresh, and bootstrap all call it.

### 2. XpozClient (`app/services/xpoz.py`)

`httpx.AsyncClient` against `https://api.xpoz.ai` (`xpoz.py:12`), 15s timeout (`xpoz.py:25`).

**Auth:** Bearer header only if `settings.xpoz_api_key` is set (`xpoz.py:18-20`); otherwise requests go out **with no Authorization header at all** — a silent misconfiguration that surfaces later as a 401 `HTTPStatusError` from `raise_for_status()` (`xpoz.py:47`). `xpoz_api_key` is optional in `config.py:17`.

**Endpoints — two implemented, plus a cursor-paginated variant:**
- `get_user_live_posts` (`xpoz.py:42-61`): `GET /api/data/twitter/posts/users/{username}/live`, strips `@`, default `limit=15`, returns `data["results"] or []`. Default `fields` now include **structural flags** (replyTo*/conversationId/quotedTweetId/isRetweet), quote/bookmark counts, and entities (`xpoz.py:29-32`); note `isReply`/`isQuote`/`mediaType` do **not** exist server-side — they are derived in `services/ingest.py`.
- `get_user_live_posts_page` (`xpoz.py:36`): cursor-paginated variant used by the analytics own-posts fallback.
- `search_live_posts` (`xpoz.py:67-80`): `GET /api/data/twitter/posts/live` keyword search. The spec **explicitly rejected** keyword search for v1 ("more surface area than 'watch a short list of niche accounts' needs", spec:115) — yet it is implemented and is the *discovery* step of `discover_and_extract_niche_frameworks` (`tools/listening.py:387`): it picks which accounts the peer pipeline then reads (per-account metrics come from `get_user_live_posts_page`, not from search results), and it passes no `fields` param — fine now that no impression filter depends on search results.

**Division of responsibility (spec:86-90, restated in the module docstring `xpoz.py:3-6`):** PFM = the connected creator's *own* posts (voice extraction, later publishing); Xpoz = third-party/market listening that feeds `repurpose_caption` as `source_text`, never voice extraction. **Third-party Xpoz content still never enters `posts`** — `check_niche_trends` writes to `ListeningMatch` (`tools/listening.py:166-180`) with the spec'd field mapping (spec:104-110), including building `platform_url = https://x.com/{author}/status/{id}`. **One deliberate exception (profile-extract change):** when the PFM feed is dead, the *user's own handle* is fetched via Xpoz `get_user_live_posts` and ingested into `posts`/`user_activity` with `source="xpoz"` (`analytics.py:84-139`, `_ingest_xpoz_user_posts`) — this is still the user's own content, passes through the same `classify_post_item` policy as PFM (only authentic originals become posts; replies/RTs route to `user_activity`), and is recorded as Xpoz-sourced.

**Consumers (both agent tools, not the poller):**
- `check_niche_trends` (`tools/listening.py:119-197`): per-handle fetch of last 10 tweets, **absolute like-count threshold** (`min_likes=50` default) — exactly the spec's recommended v1 spike approach ("absolute engagement threshold on a single fetch", spec:118-120; the spec's "open question" resolved as the flat-number option). Dedupes per `(profile_id, platform_post_id)` in Python (`tools/listening.py:156-163`) rather than relying on the DB unique constraint.
- `discover_and_extract_niche_frameworks` (`tools/listening.py:387-474`): keyword search → distinct author handles → `run_peer_pipeline` (per-account `get_user_live_posts_page` fetch → baseline → winners → blind tagging → lift → synthesis → persistence).

**Still missing vs spec handoff (spec:165-171):** the spec said the listening poll should *extend* `app/background/poller.py`'s tick with a tracked-handle store — it doesn't; the tick now runs `backfill_profile_posts` (metrics) + `check_trending` (own-posts spike path) for due configs only, and handles still come from ad-hoc tool arguments. There's still no persistent "handles a profile listens to" store; handles are passed ad hoc per tool call. Xpoz pricing/plan/rate limits remain unconfirmed (spec:175).

### 3. metrics.py (`app/services/metrics.py`)

- `X_CHAR_LIMIT = 280` (`metrics.py:3`) — oddly lives in the metrics module and is imported by `enforcement.py:6`; a constants/model module would be a better home.
- `_likes_per_hour` (`metrics.py:6-10`): `(newer.likes - older.likes) / hours`, guarding `hours <= 0` → `0.0`. Note: no guard against *decreasing* likes (negative velocity possible if counts drop).
- `current_and_baseline_velocity` (`metrics.py:13-26`): sorts snapshots by `captured_at`; `current` = rate between the two newest snapshots, `baseline` = rate between the pair before that (or `0.0` with < 3 snapshots). Consumers: `detect_spike` and `routers/alerts.py:49` (which does surface the baseline in the `AlertVelocity` payload).
- `detect_spike` (`metrics.py:29-41`) — **rewritten** (pre-existing earlier-session work): no more threshold parameter or baseline-discard. It now enforces `SPIKE_FLOOR_LIKES_PER_HOUR = 5.0` (an absolute floor so a 0.1→0.2 baseline jump can't "spike") **and** `current >= SPIKE_MULTIPLIER * baseline` with `SPIKE_MULTIPLIER = 3.0`, with a fast-path `current >= SPIKE_FLOOR_LIKES_PER_HOUR * 10` short-circuit. Consumed by `tools/listening.py:85` as `detect_spike(list(snapshots))` (single argument — the old `threshold=` call sites are gone).

**Snapshot accumulation (fixed):** `app/services/ingest.py:store_raw_item` inserts each post's first `MetricSnapshot` and appends follow-ups per the milestone policy (24h/72h/7d/30d, min 6h gap when unchanged, skip unchanged >7d unless a milestone crosses; `app/analysis/metrics.py:27-30,147+`), and `_ingest_pfm_feed`, `_ingest_xpoz_user_posts`, and `backfill_profile_posts` all route through it — so ≥2 snapshots per post **do** accumulate across analytics GETs and backfill runs, and `detect_spike` can fire. The old claim that `MetricSnapshot(` appears only at the two backfill sites is stale: the only construction site is now `ingest.py:423`. Remaining gap: `background/poller.py` only fetches on its tick for profiles with a non-`demo-` `pfm_account_id` (`poller.py:36-43`); without a valid `PFM_JWT_TOKEN` alerts still wait for an ingest-triggering request, and the Jev backstop in `check_trending` covers velocity-dead posts with ≥50 likes in the meantime.

### 4. enforcement.py (`app/services/enforcement.py`)

- `check_length` (`enforcement.py:23-26`): `len(text) > limit` (default `X_CHAR_LIMIT`) → fail with char-count feedback.
- `check_must_keep` (`enforcement.py:29-33`): case-insensitive substring containment for each required phrase; missing list joined into feedback.
- `judge_caption` (`enforcement.py:36-53`): opens `AsyncTypeSafeClient` per call (no shared client/pool), calls `client.system_one(state={"original", "rewrite"}, questions={"preserves_meaning": Noul(...)})` and thresholds `answer.noul >= 0.5` for a `"yes"/"no"` verdict (`enforcement.py:52`).
- `enforce` (`enforcement.py:56-62`): runs length → must-keep, short-circuits on first failure, then the judge.

**Spec drift & bugs (spec:211-253):**
- **Jev-down fallback is unimplemented — confirmed.** Spec:238: "if Jev is unavailable … fall back to the small Llama on Groq as the judge." `judge_caption` has no try/except; a TypeSafe outage raises straight out of `enforce` → out of the `repurpose_caption` tool (`tools/repurpose.py:74`) → `run_agent_loop`'s unguarded `call_tool` (`agent/loop.py:139`) → **unhandled 500 on `POST /chat`** (`routers/chat.py:44-46` has no try/except; only `/chat/stream` catches, `routers/chat.py:65-66`). The `EnforcementResult` docstring even reserves `judge_confidence = None` for "a non-Jev fallback" (`enforcement.py:20`) — dead comment describing unimplemented behavior.
- **Judge schema is thinner than spec'd:** spec:227-230 wants `{intact: bool, confidence, missing_items: list[str]}` plus auto-retry when `confidence < 0.8` (spec:249-251). Implementation asks a single `preserves_meaning` Noul, thresholds at **0.5**, never returns `missing_items`, and never retries.
- **`must_keep_passed` mislabeling:** when `check_length` fails, `enforce` returns `must_keep_passed=False` (`enforcement.py:57-59`) even though must-keep was never evaluated — the attempt row persisted at `tools/repurpose.py:79` then records a length failure as a must-keep failure.
- Length is checked on the *rewrite only*; no normalization (URL t.co expansion, unicode NFC) — fine for MVP, worth noting.

### 5. voice.py (`app/services/voice.py`)

**`VoiceProfilePayload`** (`voice.py:11-44`): pydantic v2 model with defaults for most fields (`posts_analyzed_count=0`, `archetype_name="Social Creator"`, `perspective`, `call_to_action_style`, `target_length_words`, `representative_excerpts`); **required** (no default): `tone`, `emoji_use`, `hook_style`, `vocabulary`, `structure`, `things_they_never_do` (`voice.py:22-35`). `things_they_never_do` accepts `str | list[str]`; `to_clean_dict` (`voice.py:40-44`) joins a list with `"; "` for DB storage.

**`VOICE_EXTRACTION_SYSTEM_PROMPT`** (`voice.py:47-66`): ghostwriter/voice-analyst persona, dictates a JSON schema (unescaped braces — this prompt is *not* `.format()`ed, it's used verbatim), demands "Return ONLY JSON."

**`extract_voice_from_captions`** (`voice.py:151-191`):
1. If **both** `groq_api_key` and `openrouter_api_key` are falsy → heuristic immediately (`voice.py:156-157`).
2. Otherwise builds a `Post N:\n...` block joined by `\n\n---\n\n` (`voice.py:159-161`), calls `chat_completion_with_fallback` (`voice.py:170`).
3. **JSON-codeblock cleanup** (`voice.py:174-178`): strips whitespace, and if the content starts with ```` ``` ````, does `strip("`")` then removes a leading `json` prefix. Minor bug: `strip("`")` removes *all* leading/trailing backticks, so a response legitimately ending in a backtick (inline code) gets mangled.
4. Unwraps a top-level JSON array to its first object (`voice.py:181-182`), injects `posts_analyzed_count` (`voice.py:184`), validates via `VoiceProfilePayload(**data)` (`voice.py:185`).
5. **Any exception** (API failure, malformed JSON, pydantic `ValidationError` from missing required fields) → `_heuristic_voice_extraction` (`voice.py:189-191`, bare `except Exception`).

**`_heuristic_voice_extraction`** (`voice.py:69-148`): deterministic offline fallback. Empty captions → hardcoded "Neutral Broadcaster" profile (`voice.py:72-87`). Otherwise it computes: emoji frequency per post via a supplementary-plane regex (`voice.py:90-102`) bucketing into Never/Sparse/Frequent; average words per post (`voice.py:105-106`); booleans for questions/exclamations/linebreaks/first-person pronouns (`voice.py:108-111`) driving tone traits ("punchy, concise" vs "informative, detailed", "inquisitive", "calm/enthusiastic"), hook/structure/perspective/archetype strings, a derived `target_length_words` range (`avg-10` to `avg+15`, floored at 5), and `representative_excerpts = captions[:2]` (`voice.py:147`). Cosmetic bug: `set(emojis_found[:3])` is interpolated directly (`voice.py:100,102`), producing Python set-repr strings like `{'🔥', '💀'}` inside the profile text.

Persistence/versioning (flip old `is_current`, bump version) lives in the *tool* (`tools/voice.py:113-138`), not here — consistent with services staying DB-light.

### 6. repurpose.py (`app/services/repurpose.py`)

- **`PLATFORM_RULES`** (`repurpose.py:16-48`): four hardcoded rule blocks — `x` (<280 chars, fragmented lines, ≤1 hashtag), `linkedin` (800-2,000 chars, 3-5 trailing hashtags, professional vulnerability), `tiktok` (50-150 words, curiosity hook, comment-bait CTA), `instagram` (150-400 words, storytelling, 3-8 hashtags). Unknown platform → silently uses the `x` rules (`repurpose.py:120`) **but still reports `platform: <unknown string>` in the output** (`repurpose.py:158`), so a typo'd platform yields X-length text labeled as, e.g., "youtube".
- **`REPURPOSE_SYSTEM_PROMPT`** (`repurpose.py:62-91`): "universal caption adaptation engine" with three rules (platform conventions / voice preservation / must-keep items), interpolating `{platform}`, `{voice_profile_context}`, `{platform_rules}` via `.format()` — JSON braces are correctly escaped (`{{` `}}`, `repurpose.py:83-88`).
- **Voice context** (`_format_voice_context`, `repurpose.py:94-109`): pulls 6 payload keys with per-key fallbacks; None/empty profile → canned "Tone: authentic, conversational founder…" line (`repurpose.py:96`). `representative_excerpts` appended via `json.dumps` (`repurpose.py:108`).
- **Output model:** `PlatformRepurposeOutput` (`repurpose.py:56-59`) requires `platform` + `adapted_text`, `changes` defaults to `[]`; `ChangeRecord` = `{change, reason}`.
- **JSON parsing** (`repurpose.py:143-153`): identical backtick/`json`-prefix cleanup and array-unwrap as voice.py (copy-pasted — two near-identical cleanup blocks remain across `voice.py` and `repurpose.py`; a shared `parse_llm_json` helper is an obvious refactor; the third copy went away with `frameworks.py`'s deletion).
- **Silent fallback** (`repurpose.py:155-163`): on *any* exception returns `{platform, adapted_text: source_text, changes: [{"change": "Kept original text", "reason": "Fallback mode"}]}`. Because the tool then enforces and persists this (`tools/repurpose.py:71-85`), an LLM outage produces a `RepurposeAttempt` containing the *unmodified* source caption; the only tell is `changes[0].reason == "Fallback mode"` — no `fallback: true` flag, nothing in the structured result distinguishes it for the agent. (Must-keep will still pass since source text contains the phrases; length check likewise.)
- Enforcement is deliberately **not** done here — it moved into `app/services/repurpose_flow.py` (`enforce` + `needs_retry` per attempt), so the generator service stays a pure LLM call. The spec's "retry one tier up on low confidence" (spec:251) is **now implemented** as: attempt 1 at the routed tier, then one judged retry at `large` with `retry_feedback` when `needs_retry(result)` — max two attempts (`repurpose_flow.py:88-115`).

### 6b. repurpose_flow.py + `POST /repurpose` (added 2026-10-25)

- **`app/services/repurpose_flow.py::run_platform_repurpose(source_text, platform, voice_profile, must_keep_phrases, route_label)`** — the single pipeline both callers share: `classify_difficulty` → route tier → up to 2 `generate_platform_repurpose` attempts (attempt 1 at the routed tier, judged retry at `large`) → `enforce(..., limit=platform_char_limit(platform))` → `RepurposeOutcome` (dataclasses `AttemptRecord` / `RepurposeOutcome`, no DB ids). **Deliberately DB-free** so no session is ever held across an LLM call. `RepurposeOutcome.fell_back` is True when the generator returned the source unchanged.
- **`app/routers/repurpose.py`** (`POST /repurpose`, registered `main.py:101`) — the webapp composer's auto-recaption path. One read session (profile: the request's `profile_id`, else the first profile; plus its current voice profile) → `asyncio.gather` one flow run per platform → **one batched commit** of every success (`repurpose_requests` + `repurpose_attempts`, one request row per platform). Platform ids are normalized through `PLATFORM_ALIASES` (frontend ids → rule sets: `twitter|bluesky|farcaster → x`, `facebook → instagram`, `youtube → linkedin`, `linkedin|tiktok|instagram` native); any unknown id is a **422**, never silently aliased. Per-platform failures come back as honest `ok: false, error` entries — only successes are persisted — and `fallback: true` marks a generator passthrough so a client never presents unchanged text as generated. 422 on empty `source_text`, 404 when no profile exists. No auth (same demo posture as every other route).
- **Tests**: `tests/test_repurpose_endpoint.py` (endpoint, alias map, validation, partial failure, fallback flag, core retry loop, tool return-shape lock) + `tests/test_tool_tiers.py` (restored `cost="llm"` / `side_effects="writes_db"` metadata). Contract also locked in `docs/flow-map.md` §"AI recaption for the webapp composer".

### 7. frameworks.py (`app/services/frameworks.py`) — deleted 2026-10-26 (Prompt 3)

- The one-shot "elite social media strategist" summary is gone with the file: `ContentPillar`/`PostFramework`/`PeerFrameworkPayload` models, `FRAMEWORK_EXTRACTION_SYSTEM_PROMPT`, `extract_peer_frameworks` and, with it, the canned "Milestones & Shipped Tech" exception fallback that used to be served as analysis.
- Its job is split across the peer pipeline: winner selection + blind tagging + lift-grounded narrative live in `app/analysis/{winners,extract,lift,synthesize}.py`, orchestrated by `app/services/peer_pipeline.py`; the `peer_frameworks` payload shape the store/Chroma path expects is built by `legacy_payload_from_report` (report-derived only — `percentage_of_posts` stays 0 with the reason stated, never invented).
- Consumers updated in the same change: `tools/listening.py` (the tool) and `background/bootstrap.py` (`_ensure_peer_frameworks`).

### 8. analytics.py (`app/services/analytics.py`) — rewritten

`get_profile_analytics(profile_id)` (`analytics.py:141-282`), consumed by `routers/profiles.py:103` and `tools/analytics.py:23`.

- **Ingest — shared policy.** Zero posts → `_ingest_pfm_feed` (`analytics.py:36`); still empty → `_ingest_xpoz_user_posts` (`analytics.py:84`) via the profile handle (the working path while the PFM feed 401s). Both delegate to `app.services/ingest.py:store_raw_item`, so classification (replies/RTs → `user_activity`), truncation flag, `last_seen_at`, deletion-suspect detection, snapshot policy, profile snapshots, and weak timezone inference are **identical by construction** with `backfill_profile_posts`. Errors are logged (not `debug`-silent like the old code).
- **Display — NULL-safe, no fabrication.** Sums use `or 0` for display only (`analytics.py:185-188`). The fabricated branch (demo `28450` impressions, `or 40.0`/`or 35.0` fake allocation percentages, invented `saves_series`, synthetic linear ramp, three fictional top posts) is **removed**: `is_live_data` false now returns zeros + an honest summary (`analytics.py:192-213`), `is_live_data: False`.
- **Pairing by `post_id`** (`analytics.py:216-225`): posts pair with their snapshots via a dict keyed on `post_id` — the old positional `zip(posts, snapshots, strict=False)` misalignment is gone.
- **Trend series** are normalized deltas from real snapshots only (`analytics.py:236-245`); `top_posts` rank by real views (`:257-261`); allocation keeps the word-count heuristic but reports real percentages (a genuine 0% stays 0%).
- Side effect on GET remains by design: the route performs ingest + commit (incremental, ≤ `INCREMENTAL_REFRESH_LIMIT = 20` items per pass).

### 9. Tests (`lumi/tests/`, config in `pyproject.toml:32-34`)

**Pytest config:** `asyncio_mode = "auto"` (bare `async def` tests run without markers) + `pythonpath = ["."]` (`pyproject.toml:32-34`); dev deps `pytest>=9.1.1`, `pytest-asyncio>=1.4.0` (`pyproject.toml:36-41`). No `conftest.py`, no coverage plugin/config, no markers, no CI config. Total: **422 tests across 40 files** (verified `uv run pytest -q` / `--collect-only` on 2026-10-27) (up from the original 20/5; includes `tests/test_profile_extract_fixes.py` — a large run against an in-memory SQLite DB covering classification, snapshot policy, deletion suspects, timezone inference, migration data fixes, NULL handling, analytics post_id pairing, and `own_lift` — plus schema/loop/memory/jev suites from earlier sessions, MCP connector + handle-search + handle-DB suites, the 2026-10-21 LLM-failure fix suites: `test_provider_fallback.py` (6) and `test_context_budget.py` (11), and the status `configured` tests in `test_mcp_google_router.py`).

- **`test_metrics.py` (5)**: snapshot factories with a fixed `T0`; covers <2 snapshots → (0,0), 2 snapshots → current only, 3 snapshots → both rates, spike threshold boundary (50 yes / 70 no), and baseline-ignored behavior (`test_metrics.py:38-44`). Good edge coverage of pure functions; nothing tests negative velocity or equal-timestamp snapshots.
- **`test_enforcement.py` (6)**: `check_length` over/at limit (281/280), `check_must_keep` missing/present, and two `enforce` tests using `monkeypatch.setattr(enforcement, "judge_caption", ...)` to prove the judge is skipped on must-keep failure (`test_enforcement.py:25-40`) and called with exact args otherwise (`test_enforcement.py:43-57`). **Gap:** `judge_caption` itself (the real `AsyncTypeSafeClient.system_one` call, the 0.5 threshold, the `"yes"/"no"` mapping) is never tested; no test for Jev-outage propagation; no test that a *length* failure misreports `must_keep_passed=False`.
- **`test_registry.py` (4)**: fixture registers a throwaway `test_echo_tool_for_registry_tests` and pops it from `registry._REGISTRY` on teardown; asserts decorator registration, OpenAI-style `list_tool_specs` shape, `call_tool` dispatch, and `ValueError("unknown tool")`. Solid unit isolation via fixture cleanup.
- **`test_voice.py` (4)**: heuristic structure (12 keys present, `posts_analyzed_count==5`, excerpts non-empty), empty-caption heuristic, an "LLM path" test that patches `get_settings` + `chat_completion_with_fallback` with an `AsyncMock` returning a fake completion (`test_voice.py:75-84`), and `test_extract_voice_from_captions_falls_back_when_no_keys`. **Bug/risk:** that last test (`test_voice.py:41-47`) does *not* force no keys — it relies on the ambient environment. Since `Settings` reads `.env` (`config.py:7`) and this repo ships a `.env`, if `GROQ_API_KEY` is filled the test makes a **real network LLM call** (passing only if the call succeeds *or* fails into the heuristic). Also: `Settings` marks `groq_api_key` etc. as required (`config.py:12-16`), so with no `.env` the `get_settings()` call inside `XpozClient()`/voice code raises `ValidationError` and tests fail — the suite is not hermetic. Other gaps: no test for the ```` ```json ```` codeblock cleanup, the array-unwrap branch, or `ValidationError`→heuristic fallback.
- **`test_xpoz.py` (1)**: constructs a real `XpozClient`, patches `client._client.get` with an `AsyncMock` returning a hand-rolled `FakeResponse` (avoids httpx respx), asserts `results` extraction for `get_user_live_posts("sama", limit=5)`. Redundant `@pytest.mark.asyncio` given auto mode (`test_xpoz.py:8`). **Gaps:** no test for `@`-stripping, `search_live_posts`, missing-API-key header behavior, or `raise_for_status` error paths.

**Overall coverage gaps:** `pfm.py` and `enforcement.judge_caption` (the real TypeSafe call) still lack direct tests — the peer pipeline is covered by `tests/test_peer_winners.py` / `test_peer_extract.py` / `test_peer_synthesize.py` / `test_peer_store.py` / `test_peer_pipeline_wiring.py`, `providers.py`'s chain by `tests/test_provider_fallback.py`, the listening tools by `tests/test_xpoz_resilience.py` + `tests/test_handle_db.py`, and analytics/ingest/own-lift behavior by `tests/test_profile_extract_fixes.py`. No eval harness (`eval/captions.json` and `scripts/run_eval.py` from setup.md:71-75 don't exist).

### 10. External services spec review (`lumi/.agents/external-services.md`, `setup.md`)

**Auth summary (spec:373-384 vs `config.py:9-17`):** all eight env vars exist in `config.py` and `.env.example`, including optional `xpoz_api_key`. **Stale spec row:** the env table still says `XPOZ_API_KEY` is "not yet added to `config.py`/`.env.example`" (spec:378) — it's been added at `config.py:17` and `.env.example:6`. Conversely `setup.md:11` lists the package as `typesafe-ai`; `CLAUDE.md` corrects this to `typesafe-sdk` (real PyPI name, `pyproject.toml:22`), and `setup.md:17`'s "check the package name" caveat was resolved.

**Rate limits:** PFM 5 rps / 40 rpm (spec:11-13) with a poll-every-5-min, back-off-on-429 strategy (spec:73-78) — **no client-side limiter, no 429 handling anywhere** (see §1). Xpoz limits explicitly unconfirmed (spec:175). Groq free-tier caps "check at build time" (spec:200) — never recorded.

**Model choices — drift narrowing (spec:195-198, 272-275 vs `agent/providers.py:14-30`):**
- Spec: Groq large `llama-3.3-70b-versatile`, small `llama-3.1-8b-instant`. Code: Groq primary `qwen/qwen3.8-27b` with fallback `openai/gpt-oss-120b` (`providers.py:14,30`); the small/large split exists as `TIER_MODELS` (`providers.py:22`, small `openai/gpt-oss-20b` / large `openai/gpt-oss-120b`) pinned per call by repurpose tiering (`services/repurpose.py:221` passes `model=`) — the spec'd llama IDs were never adopted.
- Spec: OpenRouter primary free `z-ai/glm-5.2:free` (and nemotron alternative), "use the `:free` suffix," "don't hardcode a single model," use the `models` array for 2-3 fallbacks (spec:278-280). Code: hardcoded `meta-llama/llama-3.3-70b-instruct`, no `:free`, no request-level models array — a paid-model risk on an API key with unknown balance (unchanged; OpenRouter returns 402 today). The spec's "don't hardcode a single model" is now honored at the *chain* level instead: Groq carries two candidates and every provider's failures fall through the nested retry (§6).
- Fallback trigger: spec pseudo-code catches `(RateLimitError, APITimeoutError, APIError)` (spec:288); code catches `openai.APIError` at **both** levels — per model, then per provider (`providers.py:143`) — then raises `RuntimeError("all LLM providers failed")` (`providers.py:161`), which voice/repurpose/frameworks each swallow into their heuristics. The spec's 429 story was implemented as model-chain fallback (qwen 413/429 → gpt-oss-120b) plus request-fit trimming (§5 3b), not sleep/backoff.

**Jev / TypeSafe (spec:211-253):** integrated via `typesafe-sdk` `AsyncTypeSafeClient.system_one` + `Noul` (correct SDK per CLAUDE.md), $0.042/MTok pricing noted. Divergences: threshold 0.5 vs spec's 0.8 (spec:249); no `intact`/`missing_items` structured output (spec:227-230); **no auto-retry "one tier up"** (spec:251); **no Llama-on-Groq fallback when Jev is down** (spec:238) — see §4 for the resulting 500s.

**OAuth flow (spec:25-32):** implemented end-to-end — `connect_account` tool → `auth-url` (`tools/connect.py:47`) → user authorizes on X → PFM redirects to `GET /pfm/callback` (`routers/pfm.py:30-69`), which is the only place a `Profile` row is created (keyed by `pfm_account_id`), matching "a profile cannot exist before step 4." Callback URL must be configured in the PFM dashboard (spec:18, `routers/pfm.py:38-39`) — an operational dependency no code can satisfy. Drift: `/pfm/connect` REST path requests the wrong permissions (§1).

**Neatlogs (spec:294-331):** partially implemented — `neatlogs.init` + client wrapping (`providers.py:66-72,82-109`) and one `@neatlogs.span(kind="WORKFLOW")` on the agent loop (`agent/loop.py:512`). Missing vs spec: init at lifespan/poller start (it's lazily initialized on first `get_providers()` call instead); the required `routing_version`/`prompt_version` tags on every LLM call (spec:322-325 — zero hits in the codebase), which the spec says the before/after eval proof depends on; all manual spans (`backfill/validate/store`, `poll/snapshot/velocity/alert`, `route/enforce_limits/must_keep/judge/retry`, spec:311-313); span flush in short-lived tasks. (Present, beyond spec: per-provider failure events via `neatlogs.log(...)` with the model name, `providers.py:152-157`.)

**Open questions resolved vs still open:**
- `listening_matches` schema (spec:140-154): stayed a scaffold; `check_niche_trends` writes all columns including the derived `platform_url` — no schema change needed so far.
- Listening spike threshold (spec:120): resolved in code as flat `min_likes=50` — the spec's "implementer's call" option chosen.
- Xpoz pricing/rate limits (spec:175): still unchecked.
- Groq free-tier limits (spec:200): still unchecked.

**Explicitly not implemented, per spec (correctly):** Entire (spec:339-351 — "do not build runtime dependencies"), cfo.ai (spec:355-369 — document, not code), Xpoz crawl registry/tweet-tracking/operations polling (spec:112-116).

**Spec drift the other direction (code ahead of / against spec):**
- `search_live_posts` + the frameworks tool use the keyword endpoint the spec explicitly deprioritized (§2).
- CLAUDE.md's "nothing calls `get_account_feed()` yet" note is stale (two callers).
- Spec's env-table note that `XPOZ_API_KEY` isn't in config is stale (it is).
- Spec says listening polling should extend `background/poller.py` (spec:162, 168) — partially done: the tick now refreshes metrics via `backfill_profile_posts` before `check_trending` (`poller.py:36-46`), so snapshots no longer depend on an inbound request; what is still missing is the spec's persistent tracked-handle store (handles remain ad-hoc tool arguments).

---

#### Top bugs / TODOs / spec-drift flags (this slice)

1. **Spike alerts — mostly fixed:** snapshots accumulate via the shared ingest policy (milestones 24h/72h/7d/30d) so `detect_spike` can fire, plus a Jev backstop (`SPIKE_JEV_LIKE_FLOOR = 50`) for velocity-dead posts — and `poller.py` now fetches fresh metrics on its own tick via `backfill_profile_posts` (`poller.py:36-43`) for any profile with a non-`demo-` `pfm_account_id`. Remaining gap: with no PFM token / no account id, the poller still cannot refresh metrics and alerts wait for an ingest-triggering request.
2. **Jev outage = unhandled 500:** no Llama fallback (spec:238), no try/except in `judge_caption`; `POST /chat` has no error guard (`routers/chat.py:44-46`).
3. **Fabricated data — all removed (frameworks path closed 2026-10-26):** the analytics demo numbers (28450 / 14.8% / TXT 52.4%), synthetic trend, and invented `saves_series` are **gone** (NULL-safe, honest zeros/empties instead), and `frameworks.py`'s canned "Milestones & Shipped Tech" fallback was **deleted** with Prompt 3 — no fabricated-analysis path remains; an unsupported peer run now returns `insufficient_data`/`failed` with zero frameworks.
4. **`zip(posts, snapshots, strict=False)` misalignment — fixed:** posts pair with snapshots by `post_id` (`analytics.py:216-225`); no positional pairing remains.
5. **`/pfm/connect` requests wrong OAuth permissions** (`routers/pfm.py:23`: `read/write` vs spec'd `posts/feeds`) — that path can't fetch history/metrics.
6. **Spec'd retry/fallback machinery absent:** no model tiering (qwen3.8-27b everywhere), no 0.8-confidence auto-retry, no 429 backoff at the client level (the deep backfill catches 429 and stops cleanly, but there's no retry), no neatlogs `routing_version`/`prompt_version` tags (required for the eval proof).
7. **Test suite non-hermetic and narrow:** 422 tests across 40 files now, but `test_voice.py:41-47` can still hit the real LLM depending on `.env`; clients constructed in tests require all required settings keys to exist; `pfm.py` still lacks direct tests.
---

## Frontend

Location: `lumi/frontend` (Vite SPA, no SSR). All file references below are relative to `frontend/`.

### 1. Stack & tooling

- **Framework**: React 19 (`react`, `react-dom` `^19`, `package.json:16-17`) with `@vitejs/plugin-react` `^6.0.1` (`package.json:22`).
- **Build tool**: Vite `^8.3.4` (`package.json:24`); `vite.config.ts:4-9` is minimal — only the React plugin and `server.port = 3010`. **No `/api` proxy and no `define`/env handling**; the API origin is hardcoded (see §4).
- **TypeScript**: `typescript` `^7.0.2` (`package.json:23`), `tsconfig.json:2-14` — `strict`, `noEmit`, `moduleResolution: "bundler"`, `jsx: "react-jsx"`, `types: ["vite/client"]`. `include` is `["src", "vite.config.ts"]` (`tsconfig.json:15`) so **`tests/` is not typechecked** by `npm run typecheck`.
- **Scripts** (`package.json:6-11`): `dev` → `vite --port 3010`, `build` → `vite build` (default output `dist/`), `typecheck` → `tsc --noEmit`, `test` → `node --test tests/formatDuration.test.ts tests/scriptPlayer.test.ts tests/revealEngine.test.ts`. No lint script, no ESLint/Prettier config in the tree.
- **Test runner**: Node's built-in `node --test` executing TypeScript directly (native type-stripping; requires Node ≥22.6/23). No vitest/jest.
- **Runtime deps of note**: `clsx` (class merging), `glimm` (WebGL "shader sweep" border animation used by PromptBar), `liveline` (live chart component used by InsightCards) — `package.json:12-18`.
- **Fonts**: DM Sans, Instrument Serif, Outfit loaded from Google Fonts in `index.html:7-12`; favicon `/lumi.png` (`index.html:6`). Title "Lumi Agent" (`index.html:13`).
- A stray `dev.log` (Vite dev-server output, Vite v8.3.3) is committed at the frontend root; `pnpm-lock.yaml` exists but no `package-lock.json` → pnpm is the intended package manager.

### 2. App shell

- **Entry**: `src/main.tsx:8-12` — `createRoot(...).render(<StrictMode><App/></StrictMode>)`, importing three global stylesheets (`global.css`, `theme.css`, `animations.css`) at `main.tsx:4-6`.
- **No router.** There is no react-router (or any router) dependency. Navigation is a single `view` state machine inside `App`: `"chat" | "chronic" | "settings"` (`App.tsx:284`), switched by `SidebarNav.onNavigate`/`onOpenSettings` (`App.tsx:791-799`) and rendered by a ternary in `App.tsx:802-938`. URL is only read once for an auto-send easter egg: `?say=<text>` sends a message on first mount when the chat is empty (`App.tsx:767-773`).
- **Layout composition** (`App.tsx:775-942`): `.page` → `<AmbientBackground/>` (fixed, `z-index:-1`) + `.shell` flex row = `<SidebarNav fill …/>` + `<main>` containing either `Settings`, `ChronicOnline`, or the chat view (header → scroll `stream` → `dock` with prompt pills + `PromptBar`).
- **Chat state**: chats/messages live only in `localStorage` under `lumi_agent_chats`, `lumi_agent_active`, `lumi_agent_drafts` (`App.tsx:80-82`), loaded defensively in `loadChats`/`loadDrafts` (`App.tsx:84-118`) and persisted on every change (`App.tsx:346-353`). Module-scope `nextId`/`nextChatId` counters are re-derived from storage (`App.tsx:76-78`, `App.tsx:105-110`).
- **Scroll behaviour**: a passive scroll listener on the stream maintains `nearBottomRef` (within 96 px of bottom) for the reveal auto-scroll, and a `useLayoutEffect` auto-scrolls to new user/agent messages while respecting it (`App.tsx:421-476`). The former top/bottom edge-fade (CSS mask + backdrop-blur strips + rAF-throttled `applyEdgeGates`) was **removed 2026-10-21** at the user's request — no fade substitute.
- **Empty state**: "Lumi" wordmark plus a rotating subline (`App.tsx:844-855`); sublines live in `src/constants/sublines.ts:1-3` (a **single** entry, with a typo: *"Stay chronically online across without loosing your mind"*), rotated every 20 min + 0-5 min jitter (`sublines.ts:5-6`) with a localStorage repeat-guard keyed `lumi_subline_index` (`App.tsx:355-419`); `sessionPick` at module scope makes the pick survive StrictMode's double-effect (`App.tsx:78`, `App.tsx:391`).
- **Suggestion pills**: 2-3 random prompts from `PROMPT_POOL` (`App.tsx:60-73`); clicking one only fills the composer via `handleInput`, it does not send (`App.tsx:917-927`).
- **Theme system**: CSS custom properties in `styles/global.css:13-61` (dark defaults: `--bg`, `--text`, glass/spec/shadow/blur/easing tokens) with `body.light` overrides in `styles/theme.css:5-46` (cream `#f5f4f0`, retuned glass + shadows) and reference-design aliases `--ink/--surface/--line-strong` (`global.css:130-144`). Light mode is toggled by adding/removing the `light` class **on `document.body`** via `hooks/useLightMode.ts:16-19`, observed with a `MutationObserver` (`useLightMode.ts:7-15`); `InsightCards` re-implements the same observation privately as `useDarkMode` (`InsightCards.tsx:61-77`).
  - **Inconsistency**: `global.css:89-116` defines a full light token set under **`html.light`**, which never matches because the class is only ever set on `<body>`; that block's `--bg: #f5f5f5` also conflicts with `theme.css:6`'s `#f5f4f0`. Effectively dead/duplicated theming code.
  - `theme.css:40-45` comments reference `LoginScreen`, `OAuthCallback`, `Sidebar` — no Login/OAuth components exist in this tree (copied from another project).
- **Animations**: most `@keyframes` are global in `styles/animations.css` (materialize/orb-press/btn-press/shimmer-text/spin/fade-up/pop-in…), referenced by name from CSS modules; a few component-local ones live beside their users (`AgentThinking.module.css` defines its own `iconIn/iconOut/labelIn/labelOut` morph crossfades so they can't collide). **Gotcha found 2026-10 (shimmer freeze):** Vite/CSS-modules **renames animation names inside `*.module.css` to a scoped `_name_<hash>_<line>`**, so a module rule pointing at a *global* `@keyframes` resolves to a name that exists nowhere and silently never animates (the `shimmer-text` sweep was frozen at `background-position: 0% 0%` this way). Global-keyframe animations used from a module must be set **inline in the TSX** (see `ShimmerLabel` / `doneText`, same pattern as `ThinkingState.tsx:230`) — or the keyframes must live in the same module file. `prefers-reduced-motion` handled in `global.css:169-173` and per-component (`AgentThinking.tsx` via `usePrefersReducedMotion`, plus a `@media` block in each module).

### 3. Component-by-component

**`App.tsx` (≈1,060 lines after 2026-10-21 — controller + renderer)** — Owns chats, drafts, busy/run state, profiles, analytics, view routing, the **Stop button + AbortController** (`abortRef`, `stopRun()` aborts the stream and flushes any mid-flight reveal via `flushRef`), and **`revealingId`** (marks the one freshly-streamed reply that reveals gradually); nearly all product logic lives here rather than in hooks.

**`PromptBar/PromptBar.tsx` (957 lines) — the composer actually used.**
- Props: `variant`, `demo` (default **true**), `tall`, `placeholder`, `onSend`, `text`/`onTextChange` (controlled), `busy` (`PromptBar.tsx:250-268`). `App` renders it as `<PromptBar demo={false} text={input} onTextChange={handleInput} onSend={send} busy={busy}/>` (`App.tsx:929-935`).
- Sending: `send()` trims, requires non-empty draft *or* attachments, calls `onSend?.(draft.trim())` then clears draft/attachments/menus (`PromptBar.tsx:555-562`). Enter (no Shift, not IME-composing) sends; Escape dismisses menus; Arrow/Tab/Enter navigate the open menu (`PromptBar.tsx:827-867`). **It does not call any endpoint itself** — `App.send()` does (§4).
- Rich features: **`@`-mention = real handle search** (since 2026-10-21: menu opens at ≥2 chars, instant 0-credit paint from `/handles/saved` + 300 ms debounced refine via `/handles/search` with a stale-seq guard; avatar / follower count / db-cache-live source badges; breathing skeleton while pending, breathing dot behind instant-painted rows; picking inserts `@handle ` and fire-and-forget POSTs `/handles/select`; outside-click sets `dismissed`) with a **multi-select platform selector** (added 2026-10-25: pill row X · Instagram · TikTok · Reddit · LinkedIn at the top of the `@` menu, per-pill credit cost in the title, at least one pill stays ticked; toggling clears the stale full result, re-fetches `/handles/saved?platforms=` and re-runs the debounced search — rows get a platform chip when >1 platform is selected or the row isn't X, avatars fall back per `unavatar.io/<platform>`) and `/` command menu with keyboard selection (`PromptBar.tsx`, rows from `COMMANDS`; the demo `SOURCES` list now lives behind the `+` button → menu variant `"plus"`), model picker with fake models "Luna 6 / Luna Mini / Legacy 0.4" (`206-210`), file attachment chips (`547-553`, `755-792`), fake dictation that appends a canned string after 2.2 s (`212`, `465-477`), auto-growing textarea (`479-507`), and a `glimm` WebGL rainbow border with a "sweep" celebration when picking Luna 6 (`384-442`).
- `demo` mode runs a scripted typing demo (`AUTO_STEPS`, `PromptBar.tsx:214-236`, effect `444-463`) that is disabled in the real app.
- **BUG**: the `busy` prop is destructured but never referenced (`PromptBar.tsx:258`) — **nothing locks the composer during a run**, so users can fire concurrent sends; combined with `pendingChatIdRef` (see bugs §7) replies can land in the wrong chat.
- **Smell**: `makeShader()` temporarily replaces the **global** `Math.random` with `() => 0` to get deterministic shimmer (`PromptBar.tsx:387-399`) — restored in `finally`, but it is a process-wide mutation during construction.

**`ChatBar/ChatBar.tsx` (147 lines) — DEAD CODE.** A simpler controlled textarea composer (char counter, clear button, spinner) that is imported nowhere (grep finds only its own file + one CSS comment). Superseded by `PromptBar`.

**`Sidebar/Sidebar.tsx` (603 lines) — `SidebarNav`.** Workspace rail: monogram header + workspace dropdown (portal, `Sidebar.tsx:135-217`), collapse/expand (224px ↔ 52px, auto-collapse under 900px viewport: `Sidebar.tsx:234-239`, `299-312`), nav items **Home / Chronic Online / Settings** (`NAV_ITEMS`, `Sidebar.tsx:34-43`), "New chat" row, a searchable chat-history list with per-row delete menu (`432-580`), a light/dark toggle row (`582-588`), and a footer button (`590-599`). Row-hover highlighting is done by the local `GlideMenu` (a floating highlight that interpolates between rows, `GlideMenu.tsx:10-61`); icons are hand-rolled SVGs in `Icons.tsx`.
- **"Profile switching" does not exist**: there is no profile picker here (or anywhere). The sidebar switches *chats* and *views* only; the active X profile is always `profiles[0]` (see §4/§7). Backend `POST /profiles/{id}/select` is never called.
- **BUG/quirk**: footer button `onClick={onFooterClick ?? onNewChat}` (`Sidebar.tsx:593`); `App` passes neither → clicking the "Upgrade" footer **starts a new chat**. Workspace menu rows "New workspace"/"Sign out" are no-ops (`Sidebar.tsx:145`, `202-212`).

**`InsightCards/InsightCards.tsx` (764 lines) — analytics carousel.** Three swipeable pages (prev/next pager, follow-up pill per page): `CompareCard` (Reach vs Saves dual series, Catmull-Rom smoothed into `Liveline` points, hover crosshair + tooltip: `InsightCards.tsx:216-326`), `AnomalyCard` (spend/usage toggle with hardcoded anomaly data `ANOMALY_DATA` `333-336`), `AllocationCard` (segmented bar + legend from `allocation` array, `508-594`). Live data path: `buildCompareSeries(analytics)` (`165-214`) and `analytics.allocation` (`629-638`) replace the static baseline; an `is_live_data` "LIVE" badge shows at `715-719`.
- **BUG — renders nothing in practice**: `App` only passes `analytics` when `m.insights` is true (`App.tsx:886`), and **no message is ever created with `insights: true`** (grep: only the type field at `App.tsx:49`). So `getProfileAnalytics()` is fetched on every view change (`App.tsx:291-304`) and then never displayed.
- Static/demo leftovers: hardcoded baseline reach/saves series (`194-213`), anomaly "Dec 13 / +$1,834.66 / 82 kWh threshold" copy (`347`, `675-676`), and spend/usage metrics that have nothing to do with a social app.

**`AgentThinking/AgentThinking.tsx` (483 lines) — the live/settled tool trace** (animation mechanics ported from Claude.ai's thinking UI in 2026-10, **logic only** — all artwork is ours). Renders a collapsible header (`Thought for <formatDuration>`, or the morphing active-step label + a live `47s`/`1m 07s` clock from `formatClock.ts` **gated to appear only after 5s elapsed** — no `0s`, matching the reference whose status line shows no timer early), plus a stepped list with breathing-orb flipbook/check icons, animated trace line, cycling social icon for `kind:"social"` steps, and sample-post cards from `step.samplePosts`. Mechanics, each a small local unit: **`WorkingMark.tsx`** — a canvas-generated sprite-strip flipbook (24-frame "busy" @12fps with an orbit dot, 16-frame "calm" deeper breathe @8fps; both sheets mounted at `opacity:0.001`, the active one gets `z-index:1` + `will-change`, frames advance by rAF time-accumulation as a `translateY` on the inner strip inside an `overflow:clip` window; reduced motion freezes at frame 0). **Look (2026-10 rework, matched against a live claude.ai capture)**: 20px header window / 16px row window, **crisp clay-orange disc art (~#d97757, two-stop shade + highlight — NO glow halo; a halo at 20px reads as a fuzzy blob)** over Claude's **7px-at-20px base dot** (`.markDot`, so the mark never disappears between frames); the chevron collapse affordance is **hidden at rest, shown on header hover/focus**; the row is otherwise exactly `[mark] [label] [clock]`. **`ShimmerLabel`** — readable base text + a stacked `aria-hidden`/`inert` sweep copy carrying the travelling highlight (never paints the glyphs with the gradient itself); its `shimmer-text` animation is set **inline** (CSS-modules scoping would break the global keyframes — see the Animations gotcha); **`MorphLabel`** — old/new label share ONE grid cell for ~320ms (`useStaggered` keeps the previous value mounted) while the container's width eases between measured widths (`useLayoutEffect`); **`iconNode`** crossfade for the header icon; sr-only `role="status" aria-live` region announcing label + `running`/`done`. Props: `script`, `status`, `elapsedMs`, `index`, `startedCount`, `settled`. **`index` = first NOT-completed step (`-1` = nothing spins, header falls back to "Thinking…"); rows show a check when `final`, before `activeIndex`, or `step.detail === "Completed"`** — fed by App's `findIndex(s => s.detail !== "Completed")` (fixes the old bug-10 "always the last step spins"). Used twice: live during a run and settled above each finished agent message. Expands by default when the script is short (≤4 steps) or settled.

**`ThinkingState/ThinkingState.tsx` (438 lines) — legacy canned thinking UI.** Stage machine over fixed timings `STAGES = [800,600,1800,2600,1600]` (`ThinkingState.tsx:11`) with five hardcoded variants (`Steps`, `Reasoning`, `Search`, `Social`, `Coding` — `34-127`) containing demo rows/links. **Effectively dead**: `App` renders it only for `m.thinking` (`App.tsx:867-871`) and no message ever sets `thinking`. Its `SocialIcons.tsx` (x/instagram/linkedin/tiktok/youtube/facebook SVGs, `188-197`) *is* still used by `AgentThinking`.

**`LoadingDots/index.tsx` (35 lines) — DEAD CODE.** Three-dot spinner with `role="status"`, imported nowhere.

**`ChronicOnline/ChronicOnline.tsx` (383 lines) — "Chronically Online" listening feed.** Loads `GET /trends/matches` on mount (`78-90`), "⚡ Scan Niche Trends" button triggers `POST /trends/scan` then reloads (`92-106`). Tabs (Posts / Conversations / All Signals — replies detected by captions starting with `@`, `108-113`), topic chips (all/indie/ai/viral >100 likes) and keyword filter (`125-144`), X-styled tweet cards with `unavatar.io/x/<handle>` avatars + fallback (`273-296`), and a per-post "⚡ Repurpose in My Voice" button that bubbles `onRepurpose(caption, author)` up to `App`, which switches to chat and calls `send(...)` with a prefilled repurpose prompt (`App.tsx:809-818`).
- Hardcoded: display-name map `DISPLAY_NAMES` (`11-18`), scan handles `["sama","levelsio","karpathy","paulg","swyx"]` (`97`), **timestamp always `"1d"`** (`310`), and fabricated fallback metrics `12/24/120/14000` when `metrics` is missing (`341-353`).

**`Settings/Settings.tsx` (≈640 lines after 2026-10-21).** Seven sections (`profile`, `appearance`, `social`, `connectors`, `invitations`, `workspace`, `plan` — `Settings.tsx` `SECTIONS`) with left nav + back button. **Backend touchpoints**: `GET /profiles` to list connected accounts, `POST /pfm/connect` to start the X OAuth round trip (redirect via `window.location.href`), and — new 2026-10-21 — the **`connectors` section**: `GET /mcp/google/status` re-fetched on every section open (`configured=false` → explains which env vars to set instead of offering a dead button; `connected` → chip + granted-scope labels + token expiry; Connect/Reconnect → same-tab `GET /mcp/google/connect`, `openGoogleConsent()` from `client.ts`). Appearance writes the `body.light` class through `useLightMode`. Everything else is **pure local UI fiction**: profile name/email `alex@lumi.app`, invites/members with `SEAT_TOTAL = 10`, workspace name/monogram/URL `lumi.app/lumi`, plan "Pro $12/seat, renews Nov 7, 2026". "Save" buttons only flip a local "Saved" flag.

**`AmbientBackground/AmbientBackground.tsx` (14 lines).** Five blurred, drifting gradient orbs over a dotted grid; light-mode variant swaps to cream/dark dots (`AmbientBackground.module.css:1-21`). Pure decoration, no props/state.

### 4. API layer

Two modules, both declaring `const API_BASE = "http://localhost:8000"` (`src/api/client.ts:1`, `src/api/agent.ts:1`) — **hardcoded, no env var, no Vite proxy, no production URL**. `agent.ts` re-exports most of `client.ts` (`agent.ts:30-43`) but also **duplicates** `sendChatMessage` (`agent.ts:16-28`, with a narrower `AgentResponse` that omits `tool_executions`) and `getProfileAlerts` (`agent.ts:47-52`).

Endpoints the frontend calls (all verified to exist server-side):

| Frontend call | HTTP | Backend route | Used from |
|---|---|---|---|
| `sendChatMessage` `client.ts:32-44` / `agent.ts:16` | `POST /chat` | `routers/chat.py:44` | stream fallback only, `App.tsx:660` |
| `streamChatMessage` `client.ts:52-111` | `POST /chat/stream` (SSE) | `chat.py:54` | `App.tsx:545` — accepts `opts.signal` (AbortSignal) for the Stop button |
| `getProfiles` `client.ts:107-112` | `GET /profiles` | `profiles.py:55` | `App.tsx:292`, `Settings.tsx:58` |
| `getProfileAlerts` `client.ts:114-119` / `agent.ts:47` | `GET /profiles/{id}/alerts/unread` | `alerts.py:31` | **never called** |
| `getChatHistory` `client.ts:121-126` | `GET /chat/history` | `chat.py:85` | **never called** |
| `deleteChatHistory` `client.ts:128-137` | `DELETE /chat/history` | `chat.py:110` | `App.tsx:747` |
| `generateChatTitle` `client.ts:139-153` | `POST /chat/title` | `chat.py:128` | `App.tsx:504` |
| `getConnectAuthUrl` `client.ts:156-169` | `POST /pfm/connect` | `pfm.py:17` | `Settings.tsx:227,249` |
| `getTrendMatches` `client.ts:188-197` | `GET /trends/matches` | `trends.py:43` | `ChronicOnline.tsx:81` |
| `scanNicheTrends` `client.ts:199-211` | `POST /trends/scan` | `trends.py:75` | `ChronicOnline.tsx:95` |
| `getProfileAnalytics` `client.ts:238-246` | `GET /profiles/{id}/analytics` | `profiles.py:101` | `App.tsx:298` |
| `searchHandles` `client.ts` (handle-search section) | `GET /handles/search` (+ `platforms` CSV arg) | `handles.py` → MVP `api_search` | `PromptBar.tsx` (debounced `@` menu, re-runs on platform toggle) |
| `getSavedHandles` `client.ts` (+ `platforms` CSV arg) | `GET /handles/saved` | `handles.py` → MVP `api_saved` | `PromptBar.tsx` (mount snapshot, on platform toggle, after search/select) |
| `selectHandle` `client.ts` | `POST /handles/select` | `handles.py` → MVP `api_select` | `PromptBar.tsx` (on pick, fire-and-forget) |
| `getGoogleConnectorStatus` / `openGoogleConsent` `client.ts` | `GET /mcp/google/status` / `GET /mcp/google/connect` | `mcp_google.py` | `Settings.tsx` connectors section (status per open; consent = same-tab navigation) |

- **Streaming**: `streamChatMessage` POSTs `{profile_id, message}` (optionally with `signal: AbortSignal` — the **Stop** button aborts it), reads `response.body` with a `TextDecoder`, splits on `\n`, parses `data:` lines as JSON `StreamEvent`s (`tool_start` / `tool_done` / `done` / `error`, typed at `client.ts:46-50`) and accumulates the final `done` payload (`client.ts:70-104`). Non-streaming `POST /chat` is only the catch-path fallback (`App.tsx:654-678`) — and **never runs on abort**: the catch checks `controller.signal.aborted` first and appends an honest "⏹ Stopped — I didn't finish that." instead (retrying would re-run the whole agent turn server-side). Backend-side, a client disconnect does *not* cancel the server's agent loop (documented limitation) — Stop stops the reading, not the turn.
- **Smooth reveal (added 2026-10-21, `src/reveal/`)**: the backend sends no token streams — the full reply arrives in one burst at `done` — so `revealingId` marks the freshly appended reply and `AgentMessage` renders it through `useSmoothText(target, animate)` → `target.slice(0, shown)` advanced by a rAF loop over the pure `revealEngine.ts` (`BASE_CPS=60`, `CATCHUP=6` per backlog char, `MAX_CPS=1500`, surrogate-pair-safe slicing). Adaptive speed keeps catching up after the stream ends; Stop flushes instantly; `prefers-reduced-motion` shows text immediately; auto-scroll pins to bottom each frame **only while near bottom** (existing 96 px threshold via `nearBottomRef`); the existing markdown parser runs over the partial text (no per-word fade — unclosed tokens fall back to plain text). History/reloads/chat-switches render full text (reveal plays once, right after streaming).
  - **Duplicate-id fix (2026-10-21, verified live)**: the reveal initially never played in the dev session — Vite Fast Refresh re-ran the `App.tsx` module (resetting the module-scope `nextId` to 1) while React state survived, so new messages reused existing ids. With `key={m.id}` colliding, an *old* fully-shown message matched `animate={m.id === revealingId}`; its settled `onRevealDone` cleared `revealingId` within one frame of the new reply mounting, so the `!active` branch rendered the full text instantly (zero rAF ticks — proven with an rAF spy). Fixed three ways: `loadChats` now reissues duplicate message ids it finds in storage (heals the stored duplicates this bug created); the module re-derives `nextId`/`nextChatId` from storage on every module execution (`loadChats()` at module scope, so a hot reload can't restart the counters at 1); and a one-time mount effect reissues duplicates in live state (idempotent — returns the same reference when clean). Verified live: reply mounts empty with `rid === mid`, grows 0 → 24 → full over ~1.5 s with rAF ticks firing, then `rid` clears at settle.
- **Polling intervals: there are none.** No fetch-polling loops exist anywhere; the only timers are UI ones (100 ms elapsed-time ticker `App.tsx:270-279`, subline rotation, PromptBar demo, plus PromptBar's 300 ms handle-search debounce). The alerts endpoint defined at `client.ts:114` is dead — **unread alerts are never polled**, despite CLAUDE.md listing "polling alerts" as frontend REST surface.
- **Error handling is inconsistent**:
  - Throw with status text: `sendChatMessage`, `streamChatMessage`, `scanNicheTrends` (`client.ts:39-41`, `66-68`, `209`).
  - Silently swallow → `[]`/`null`/`false`: `getProfiles`, `getProfileAlerts`, `getChatHistory`, `getTrendMatches`, `getProfileAnalytics`, `deleteChatHistory`, `getConnectAuthUrl`, `generateChatTitle` (client-side word fallback).
  - Chat send: stream failure → console.warn + non-stream retry → error bubble `⚠️ Connection error: … http://localhost:8000` (`App.tsx:654-702`).
  - **BUG**: an SSE `{"type":"error"}` event (emitted by `chat.py:66`) is delivered to `onEvent` but never inspected in `App.tsx:545-612`; likewise a stream that ends without `done` leaves `finalResult.content === ""`, so the user gets the misleading success text *"I finished working on that — let me know if you'd like more detail."* (`App.tsx:641`) instead of the real error.
- **Profile selection**: `activeProfileId = profiles.length > 0 ? profiles[0].id : 1` — repeated at `App.tsx:544`, `App.tsx:657`, and `App.tsx:810`. Backend `POST /profiles/{id}/select` (`profiles.py:85`) is unused.
- **Tool→label mapping** in `App.tsx` matches the backend registry names (`connect_account`, `check_niche_trends`, `save_user_request`, `discover_and_extract_niche_frameworks`, `extract_voice_profile`, `repurpose_caption`); all other tools (`get_posts`, `get_analytics`, `start_listening`, `check_trending`, `submit_action`, `dismiss_alert`, `answer_style_questions`…) fall through to generic `Executing <name>…`.

### 5. Simulation subsystem (`src/simulation/`)

The "scripted demo" layer that drives the thinking-trace UI. Despite the name, **the current app runs scripts for real requests too** — `App.send()` builds a synthetic `SimScript` (`live-<runId>`) and mutates it as SSE events arrive (`App.tsx:519-612`), rather than playing a canned timeline.

- **`simScripts.ts`** — data + lookup: `SimStepKind` (`social|analysis|writing|action`), `SimStep` (label/kind/duration/detail/meta/platforms/samplePosts), `SimScript` (`id`, `steps`, `finalDelayMs`) (`simScripts.ts:1-25`). Five canned scripts (`default`, `contentMix`, `scheduling`, `lastPost`, `socials`, registry `215-221`), regex-based `pickScript(text)` keyword matcher (`194-213`, `231-236`), `scriptById()` with `DEFAULT_SCRIPT` fallback (`227-229`). **`pickScript` and `defaultScript` are never imported by the app** — only `scriptById` is used (`App.tsx:862`, for settled messages without a custom script).
- **`scriptPlayer.ts`** — pure timeline math: `jitterDuration(base, rng)` applies ±15 % jitter with a 600 ms floor (`STEP_FLOOR_MS=600`, `JITTER_RATIO=0.15`, `scriptPlayer.ts:5-11`); `buildTimeline` accumulates starts/durations + `finalDelayMs` (`20-37`); `stateAt(timeline, elapsedMs)` returns `{status, index, startedCount}` (`45-56`).
- **`useSimulatedRun.ts`** — React hook that plays a script: builds a timeline, schedules `setTimeout`s at each step start plus one at `totalMs`, and publishes `SimRunState` (`useSimulatedRun.ts:30-64`). **Dead code**: nothing imports it — `App.tsx:760-771` reimplements timing with a 100 ms `setInterval` and computes `index` as the first not-completed step (`findIndex(s => s.detail !== "Completed")`, `-1` when all done) / `startedCount = steps.length`, so `scriptPlayer` is exercised only through the hook and the tests.
- **`formatDuration.ts`** — `ms → "N seconds" / "N minutes M seconds"` with pluralisation (`formatDuration.ts:1-11`), used for the settled header `Thought for …`. It does **not** render hours as hours (60 min → `"60 minutes"`), which the tests lock in.
- **`AgentThinking/formatClock.ts`** (added 2026-10) — the compact live-header clock `ms → "47s" / "1m 07s"` (tabular seconds, never negative). Deliberately separate from `formatDuration.ts` so the settled line's tested shape can't drift; `tests/formatClock.test.ts` locks it.
- **How a run is triggered**: any `send()` starts `activeRun` with a one-step `"Thinking..."` seed (`App.tsx:519-540`), pushes a new step per `tool_start` and marks `detail: "Completed"` (+ sample posts) on `tool_done` (`App.tsx:576-611`), appends a `"Synthesizing response"` step when the stream resolves (`App.tsx:616-621`), stores the full script on the message as `message.sim.customScript` (`App.tsx:642-646`), and clears `activeRun`/`busy` in `finally` (`App.tsx:703-706`). Step `durationMs` values are decorative in the live path — pacing comes from actual SSE events.

### 6. Tests

Run via `npm test` → `node --test` on four files (no coverage of components, API layer, or App logic — the rAF loop, DOM/scroll, Stop button, and reduced-motion behaviors are **not** covered; only the pure engines are):

- **`tests/scriptPlayer.test.ts` (104 lines)**: `jitterDuration` stays within ±15 % and respects the 600 ms floor with an injected RNG (`26-38`); `buildTimeline` is cumulative, includes `finalDelayMs`, and floors short steps (`40-55`); `stateAt` walks steps in order at exact boundaries (0/999/1000/1700/2599/2600/huge) and reports `done` (`57-95`); empty script → `{status:"done", index:-1, startedCount:0}` (`97-104`).
- **`tests/formatDuration.test.ts` (29 lines)**: sub-minute rounding incl. negatives → `"0 seconds"` (`5-14`), minute boundaries incl. `"59 minutes 59 seconds"` (`16-24`), hour boundaries rendered as `60/61 minutes` (`26-28`).
- **`tests/revealEngine.test.ts` (6 tests, added 2026-10-21)**: fast 2,000-char burst reveals gradually (first frame < 100 chars) and finishes within a couple of simulated seconds; slow stream (word every 300 ms) is monotonic, per-frame-bounded, always caught up before the next chunk, still animating after the final word; mid-reveal flush shows everything then stays `done`; a shorter target resets to 0 (no leftover text); emoji/sweep never ends on a lone high surrogate; speed-constant behavior (big backlog ≫ 1-char backlog; small backlog near `BASE_CPS`).
- **`tests/formatClock.test.ts` (3 tests, added 2026-10)**: sub-minute floor (`0/999/1000/47000/59999` → plain seconds), minute padding (`1m 00s`/`1m 07s`/`2m 05s`), and negative/absurd input (`-1 → 0s`, an hour → `60m 00s`).
- Note: tests import with explicit `.ts` extensions (`../src/simulation/scriptPlayer.ts`, `../src/reveal/revealEngine.ts`, `../src/components/AgentThinking/formatClock.ts`) to satisfy Node type-stripping, and are excluded from `tsc` by `tsconfig.json:15`.

### 7. Hardcoded values, bugs, TODOs, dead code, backend inconsistencies

**No `TODO`/`FIXME`/`HACK` comments exist anywhere in `frontend/src`** (grep clean).

**Hardcoded values**
- `API_BASE = "http://localhost:8000"` ×2 (`client.ts:1`, `agent.ts:1`) and the same URL inside the error copy (`App.tsx:683`).
- Profile fallback `id = 1` (`App.tsx:544`, `657`, `810`); `getTrendMatches(profileId = 1, …)` (`client.ts:188`), `scanNicheTrends(profileId = 1, handles = ["sama","levelsio","karpathy","paulg","swyx"], minLikes = 20)` (`client.ts:199-203`) duplicated inline at `ChronicOnline.tsx:95-99`.
- Settings fiction: `alex@lumi.app` (`Settings.tsx:141,160,479`), `SEAT_TOTAL = 10` (`25`), `lumi.app/lumi` (`425`), "Pro $12 / seat / month", "renews Nov 7, 2026" (`451-466`), default name "Lumi User" (`49`).
- Backend-only user scoping mirrored in the UI: `DISPLAY_NAMES` includes `AtehOfficial` (`ChronicOnline.tsx:17`); the backend hard-filters `/profiles` to `{"atehofficial","ateh","just_ateh"}` + two PFM ids (`app/routers/profiles.py:51-66`), so "profiles" are really "this user's accounts".
- `Settings`/`Sidebar` brand constants: workspace `{key:"lumi", name:"Lumi", monogram:"L"}` (`Sidebar.tsx:32`).
- Fake product surface: models "Luna 6/Luna Mini/Legacy 0.4" and slash-commands (`PromptBar.tsx:198-210`), "128 posts, 9 drafts" source blurb (`190`), InsightCards spend/kWh anomaly numbers (`InsightCards.tsx:333-336`).

**Bugs / risks**
1. **No send lock** — `PromptBar` ignores `busy` (`PromptBar.tsx:258`), so `send()` can run concurrently; `pendingChatIdRef.current` is overwritten by the later send (`App.tsx:481`), and the *earlier* stream's reply is appended using the ref at completion (`App.tsx:629`, `656`) → **reply can be written into the wrong chat**. (The 2026-10-21 Stop button does *not* fix this — it aborts only the latest controller.)
2. **SSE `error` events are silently dropped** (see §4) → misleading success message instead of the failure reason. **Fixed:** `App.tsx` now captures `error` events, marks the live step `Failed`, and renders `⚠️ <error>` instead of the success boilerplate.
3. **`isConnectLink` heuristic** (`App.tsx:143-146`) matches any label containing `connect`/`link`/`authorize` and ignores the URL — because `"linkedin".includes("link")` is true, **every markdown link labelled "LinkedIn" (or any "link …") renders as the branded X "Connect" card** with the X bird icon (`App.tsx:185-191`).
4. **Deleting one local chat calls `DELETE /chat/history`** for `profiles[0]` (`App.tsx:746-748`) → wipes the *entire* server-side conversation for that profile, not just the deleted chat.
5. **`setActiveId` inside a `setChats` updater** in `handleDeleteChat` (`App.tsx:731-741`) — state side effect inside a reducer, invoked twice under StrictMode.
6. **`InsightCards` and `ThinkingState` never render** (see §3) — `getProfileAnalytics` on every `[view]` change (`App.tsx:291-304`) is wasted network I/O whose result is never shown.
7. **Sidebar footer "Upgrade" starts a new chat** (`Sidebar.tsx:593`).
8. `getProfiles` re-fetches on every view switch (effect dep `[view]`, `App.tsx:304`) and swallows failures, leaving `profiles=[]` → silent fallback to `profile_id=1`.
9. `PromptBar` mutating global `Math.random` during shader creation (`PromptBar.tsx:387-399`).
10. Live trace always marks the *last* pushed step active and never advances older steps to "done" until settle — **fixed 2026-10**: `App.tsx` now passes `index = findIndex(step.detail !== "Completed")` (first pending; `-1` when all done) and `AgentThinking` treats `-1` as "nothing spins", showing checks for every completed step.
11. Light-mode tokens defined twice with different values (`html.light` dead block `global.css:89-116` vs `body.light` `theme.css:5`); `InsightCards` keeps a third, separate dark-mode observer (`InsightCards.tsx:61`).

**Dead code / duplication**
- `components/ChatBar/` (whole component + 1132-line CSS) and `components/LoadingDots/` — never imported.
- `simulation/useSimulatedRun.ts` (+ therefore `scriptPlayer` at runtime), `pickScript`/`defaultScript` (`simScripts.ts:223-236`).
- `getChatHistory` and `getProfileAlerts` (`client.ts:114-126`) — defined, never called; `agent.ts` duplicates `sendChatMessage`/`getProfileAlerts`/`API_BASE` from `client.ts`.
- `Message.insights` and `Message.thinking` fields (`App.tsx:49,51`) — read but never written.
- `ThinkingState` variants and most of `PromptBar`'s demo machinery (`AUTO_STEPS`, dictation) are unreachable in the wired app.
- `theme.css` aliases for non-existent `LoginScreen`/`OAuthCallback`.

**Backend consistency**
- **All 14 endpoints the frontend calls exist server-side** (table in §4) — no phantom routes. The reverse is not true: `POST /profiles/{id}/select` (documented in `.agents/api-endpoints.md` as the profile switcher) is **never used**, and the documented `GET /chat/history` is never called, so **server chat history and the localStorage UI diverge** (only `DELETE` is wired, and then only destructively — bug 4). Unread-alerts polling is likewise unimplemented.
- Request/response shapes line up: `ProfileAnalytics` (`client.ts:213-236`) matches `app/services/analytics.py`'s return keys incl. `allocation[].textColor`, `reach_series`, `is_live_data`; `StreamEvent` matches `chat.py:64-78` + `loop.py`'s `tool_start`/`tool_done` payloads; tool names in the label map match `app/tools/*` registry names. Minor drift: `agent.ts`'s local `AgentResponse` omits `tool_executions`, and `getProfileAlerts` is typed `any[]`.
- **Scope inconsistency with the X-only MVP** (CLAUDE.md / `.agents/api-endpoints.md`): the UI advertises multi-platform flows — thinking steps tagged `["x","linkedin"]` (`App.tsx:564`), the Chronic Online repurpose prompt asks for *"X, LinkedIn, and Instagram"* (`App.tsx:814`), and `simScripts`/`ThinkingState` cycle Instagram/TikTok/YouTube/Facebook icons — while the backend is X-only.
---

## Documentation, Specs & Project Configuration

### 1. Doc map: what each file is for

The repo (`C:\Users\USER\Downloads\Lumi-agent-backend`, project in `lumi/`) has a 4-layer documentation system:

| Layer | Files | Role |
|---|---|---|
| Architecture overview | `lumi/README.md` (159 lines) | What Lumi is, stack, architecture diagram, directory layout, the 11-table DB summary, tool list, endpoint table, env vars, run/deploy/migrations instructions, live Railway URL |
| AI-agent guidance | `lumi/CLAUDE.md` (51 lines) | Guidance for Claude Code: commands, architecture rules (no `create_all()`, voice-profile versioning flush, tools registration side-effect), OAuth connect flow, env vars, gotchas. Explicitly says `.agents/*.md` are source of truth over it (CLAUDE.md:9) |
| Process + roadmap | `lumi/CONTRIBUTING.md` (133 lines) | Day-to-day workflow: setup, the task list, where-things-live rules, DB change workflow, conventions, full git workflow, commit style, and the `.agents/` "Specs" pointer (CONTRIBUTING.md:125-133) |
| Planning specs (source of truth) | `lumi/.agents/setup.md`, `api-endpoints.md` (130 lines), `database.md` (143 lines), `external-services.md` (269 lines) | Pre-build specs: scope + directory plan; exact request/response shapes; column-level schema per table; confirmed external API endpoints (PFM, Groq, OpenRouter, Jev/TypeSafe, neatlogs) with rate limits and the real OAuth flow |
| Per-layer deep dives | `lumi/docs/*.md` (8 files) | Short logic-focused notes: `README.md` (index), `models.md`, `routers.md`, `tools.md`, `agent.md`, `services.md`, `background.md`, `frontend-integration.md`. Each "meant to be read in under two minutes" (docs/README.md:13) |
| Hook/tooling config | `.agents/hooks.json`, `.claude/settings.json`, `.entire/settings.json`, `package.json`, `railway.json`, `alembic/README`, `.gitignore`, `pyproject.toml` | Entire (project-record tooling) hooks for two agent CLIs; npm monorepo scripts; Railway deploy config; generic Alembic stub |

Relationship: README = big picture; CLAUDE.md = AI orientation + hard rules; CONTRIBUTING = process + the de-facto roadmap; `.agents/*` = the contract the build was planned against (and per CLAUDE.md:9, the override when docs disagree); `docs/*` = why each layer works the way it does, written later and closer to the code.

### 2. CONTRIBUTING task list — the de-facto roadmap

From CONTRIBUTING.md:31-59, "roughly in the order they unblock each other". Unchecked tasks, compactly:

1. **Populate the tools that still stub their logic** (CONTRIBUTING.md:35). `extract_voice_profile`'s payload and `repurpose_caption`'s `_draft_rewrite` claimed to return placeholder/passthrough text (`# TODO` in `app/tools/voice.py`, `app/tools/repurpose.py`). "Start here; nothing downstream (enforcement, the judge, user actions) means anything until these return real output."
2. **Get real keys into `.env` / Railway dashboard** (CONTRIBUTING.md:36-40): `GROQ_API_KEY`/`OPENROUTER_API_KEY` (needed for task 1 to run at all), `NEATLOGS_API_KEY` (wrapping in place but untested against a real account), `TYPESAFE_API_KEY` (Jev early access; confirm `judge_caption` returns a real verdict), `PFM_JWT_TOKEN` (needed for `connect_account` and backfill/polling).
3. **Register the Post for Me callback URL** (CONTRIBUTING.md:41). OAuth flow implemented, but PFM redirects to whatever URL is configured in *their* dashboard — someone with access must point it at `<deployed-app>/pfm/callback`.
4. **Replace placeholder seed data with real accounts** (CONTRIBUTING.md:42). `seed.py`'s three demo profiles had fake `pfm_account_id`s and zero posts; after callback registration, connect three real X accounts (keep one low-post-count for the style-question fallback), then backfill.
5. **Build the backfill/polling pipeline on top of `get_account_feed`** (CONTRIBUTING.md:43). Client method confirmed working; nothing called it (at time of writing); needs a tool/background job that pages it into `posts`/`metric_snapshots`, respecting PFM rate limits (5 req/s, 40/min).
6. **Revisit the alerting logic** (CONTRIBUTING.md:44). Beyond "no data yet": the old hardcoded `SPIKE_THRESHOLD_LIKES_PER_HOUR = 20.0` was replaced by a floor × own-baseline multiplier plus a Jev backstop (§3, Services §3); `repurpose_caption` never clears `alerted_at`/`alert_dismissed` — only `dismiss_alert` does.
7. **Build social listening on Xpoz — keep it simple** (CONTRIBUTING.md:45-48). Use exactly one endpoint (`GET /api/data/twitter/posts/users/{username}/live`), skip Xpoz's tracking registry. Need: `app/services/xpoz.py` (`XpozClient`), a place to store tracked handles, a tool/poller writing `listening_matches`, and a decision on how the unread-alerts endpoint surfaces them. `listening_matches` columns are a "starting scaffold, not fixed". Not a blocker: `repurpose_caption` already takes raw `source_text`.
8. **Add the Jev-unavailable fallback** (CONTRIBUTING.md:49). Spec says fall back to a small Llama model on Groq; `enforcement.py` doesn't implement it — a Jev outage just raises.
9. **Wire up the frontend through `/chat`** (CONTRIBUTING.md:50). Almost everything goes through `POST /chat`; resist growing the REST surface — new frontend needs are "almost always a reason to add an agent tool, not a new endpoint."
10. **Add tests for DB-dependent foundations** (CONTRIBUTING.md:55-58, needs real Postgres): voice_profiles version-flip ordering, posts alert-once behavior, agent loop's `MAX_TOOL_ITERATIONS` cutoff.
11. **Set `repurpose_requests.route_label`** (CONTRIBUTING.md:59). **Done 2026-10-25** — `app/services/repurpose_flow.py` calls `classify_difficulty` and both writers persist `outcome.route_label`; CONTRIBUTING's "Nothing populates it" is stale.

Completed tasks (marked `[x]`): deploy the app to Railway (`lumi-api` service, live at `https://lumi-api-production-6260.up.railway.app`; `/chat` noted as 500ing due to placeholder keys) and add the pure/mocked test suite.

### 3. Git / workflow conventions

- **Nobody commits to `main`** — not even a one-line fix (CONTRIBUTING.md:91). Branch off `main`, name `<yourname>/<short-description>` or `<area>/<short-description>` (`gbemike/pfm-backfill`, `listening/xpoz-client`); no enforced convention (CONTRIBUTING.md:93).
- **Pre-PR gate**: `uv run ruff check .` then `uv run pytest` (CONTRIBUTING.md:95-100). If something can't be unit-tested, say so in the PR description.
- **Smoke-test the exact production start command** before the PR (CONTRIBUTING.md:101-109): `export PORT=8080; uv run alembic upgrade head; uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`, then `curl localhost:8080/health` → `{"status":"ok"}` — "it's the literal command Railway runs."
- **Post-merge deploy**: `railway up --service lumi-api` from `main`, then `curl https://lumi-api-production-6260.up.railway.app/health` (CONTRIBUTING.md:111-115).
- **Commit style**: documented as `<verb>: <what>` with examples `add: chat, profiles, and alerts routers`, `fix: profile.name regression in select_profile` (CONTRIBUTING.md:118). No force-push to `main`; don't touch `entire/*` branches (Entire checkpoint branches); don't commit `.env` or `.entire/` (CONTRIBUTING.md:119-121).
- **No CI, no staging env yet** — "deploy safety" is the local smoke test; a second Railway environment is the suggested next step (CONTRIBUTING.md:123). CI "if/when we add it" will enforce ruff (CONTRIBUTING.md:83).
- **DB changes**: edit SQLModel → autogenerate against a live (can be empty) Postgres → read the generated migration → apply locally → commit model + migration together (CONTRIBUTING.md:68-79).

### 4. Known gotchas (documented across files)

- **`railway.json` is silently ignored by Railway** — Config-as-Code deprecation warning on a fresh service; start/predeploy/healthcheck had to be set directly in service settings. Keep the file as "documentation of intent" but verify build logs for "No start command detected" (README.md:146-150; CONTRIBUTING.md:52). Current `railway.json` still documents RAILPACK builder + `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`, predeploy `uv run alembic upgrade head`, healthcheck `/health`.
- **Always pass `--service` to `railway up`** — the first deploy went to the *existing Postgres service* because no `--service` flag was given with a project already linked (README.md:144; CONTRIBUTING.md:53).
- **PyPI package is `typesafe-sdk`, not `typesafe-ai`** (redirect shim) — used in `app/services/enforcement.py` (CLAUDE.md:47). Note: `.agents/setup.md:11,17` still lists `typesafe-ai` (with a "check against their docs" caveat) — the spec is stale on this point vs `pyproject.toml` (`typesafe-sdk>=0.7.4`).
- **PFM docs are a JS-rendered Scalar UI** — fetch `api.postforme.dev/docs/json` for the raw OpenAPI spec; confirmed endpoints already extracted into `.agents/external-services.md` (CLAUDE.md:48).
- **Alembic autogenerate SQLModel import gap** — can render `sqlmodel.sql.sqltypes.*` types without importing sqlmodel; `alembic/script.py.mako:12` now forces `import sqlmodel`, but partial indexes / renamed columns (drop+add) still need manual review (CLAUDE.md:17; CONTRIBUTING.md:77; verified: the mako template does force the import).
- **PFM vs Xpoz are not interchangeable** — never write Xpoz results into `posts`; `posts` is PFM-backfilled, `profile_id`-owned, voice-extraction-only; `listening_matches` is for Xpoz third-party content feeding `repurpose_caption` only (CLAUDE.md:50; docs/models.md:31-33).
- **`voice_profiles` versioning** — insert a new current row only after flipping the old row and flushing, or the partial unique index fails (CLAUDE.md:26; docs/models.md:7-18).
- **Tool registration is an import side effect** — a new tool module must be imported in `app/tools/__init__.py` or it never registers (CLAUDE.md:29; docs/tools.md:7-13).
- **`/pfm/callback` returns bare JSON** — a real user finishing OAuth lands on a blank JSON page; no redirect back to the frontend app yet, "not decided yet" (docs/frontend-integration.md:108; verified in `app/routers/pfm.py:42-69`).
- **`repurpose_caption` doesn't clear alerts** — only `dismiss_alert` does; flagging rather than deciding behavior (docs/background.md:14; CONTRIBUTING.md:44).
- **Alerts endpoint is always empty** until metrics ingestion exists; frontend polls it every 5–10s (docs/routers.md:17; docs/frontend-integration.md:118).

### 5. Contradictions / staleness BETWEEN docs and code

The biggest finding: **the codebase has moved well past the docs, and nearly every doc still describes the hackathon-weekend state.** Highlights:

- **Seeded profiles**: README.md:43 ("Seeds 3 demo profiles"), README.md:159 ("Three seeded X accounts"), CLAUDE.md:7,33, `.agents/setup.md:69,98`, `.agents/database.md:12` all say 3 demo profiles — but `app/seed.py:11-16` now seeds **one real account** (`AtehOfficial`, `pfm_account_id="spc_U8xOuoxKCYpKAbzUymPCd"`) with a docstring saying "Ensure only the user's connected accounts exist, purging all third-party accounts." CONTRIBUTING task 4 ("replace placeholder seed data") is effectively done, differently than planned.
- **Tool stubs**: CONTRIBUTING.md:35 says `extract_voice_profile` and `repurpose_caption` return placeholder text with `# TODO` markers — no `TODO`/`_draft_rewrite` stub remains in `app/tools/{voice,repurpose}.py`. Real implementations now live in `app/services/voice.py` (`extract_voice_from_captions` with LLM prompt + heuristic fallback) and `app/services/repurpose.py` (`generate_platform_repurpose` with `PLATFORM_RULES`). Task 1 is stale.
- **`get_account_feed` "not consumed by anything"**: CLAUDE.md:49, docs/services.md:11, CONTRIBUTING.md:43 — but `app/services/voice.py:28` (`_attempt_pfm_backfill`) and `app/services/analytics.py:33` both call it. Task 5 partially done.
- **"Nothing constructs a MetricSnapshot"**: docs/services.md:20 (claim since removed — **resolved**) — construction now lives in `app/services/ingest.py:store_raw_item`. The "inert, not just incomplete" claim about spike detection is at least partially outdated.
- **"No XpozClient, no tool"**: CLAUDE.md:50 and docs/models.md:33 — `app/services/xpoz.py` defines `XpozClient` (`get_user_live_posts`, `search_live_posts`), and `app/tools/listening.py:166` writes `ListeningMatch` rows (tool `check_niche_trends`). Task 7 substantially progressed.
- **X-only scope vs multi-platform repurpose**: README.md:5 ("MVP scope: X only… targets X's 280-character format"), CLAUDE.md:7, `.agents/api-endpoints.md` ("All tools operate on X… the `platform` field is always `x`") — but the repurpose tool now accepts `x|linkedin|tiktok|instagram` (`app/tools/repurpose.py:15,25,36`) with per-platform system prompts in `app/services/repurpose.py:16`. Direct contradiction with the headline scope claim.
- **Endpoint lists**: README.md:86-92, `.agents/api-endpoints.md`, and docs/frontend-integration.md ("The five endpoints") list 5 endpoints. The code has **23 routes across 9 routers**: the 5 documented ones plus `POST /pfm/connect`, `GET /pfm/callback`, `GET /trends/matches`, `POST /trends/scan` (a 5th router file, `app/routers/trends.py`, which docs/routers.md:3 — "eight files" — doesn't know about), `POST /chat/stream` (SSE), `DELETE /chat/history`, `POST /chat/title`, `GET /profiles/{id}/analytics`, the four `GET|POST /handles/*` shim routes, `POST /voice/transcribe`, the three `GET /mcp/google/*` routes, and `POST /repurpose`.
- **Tool list**: README.md:80 lists 11 tools; the registry now has **20** (§3) — README also misses `backfill_posts`, `connect_account`, `start_listening`/`stop_listening`, `remember`, `recall_memory`, `get_posts`, `get_voice_profile`, `answer_style_questions`, `submit_action`, `dismiss_alert`, `save_user_request`, `get_user_activity`, `get_peer_advice`.
- **Model IDs**: `.agents/external-services.md:196-197` recommends Groq `llama-3.3-70b-versatile` / `llama-3.1-8b-instant` and says "do not hardcode a single model" / use OpenRouter `:free` suffixes (lines 275-281). Code: `GROQ_MODEL = "qwen/qwen3.8-27b"` (an OpenRouter-style slug pointed at Groq's base URL) with fallback `openai/gpt-oss-120b`, and `OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"` (`app/agent/providers.py:14,17,30`) — no free suffix, hardcoded chain.
- **Jev fallback**: task 8 (CONTRIBUTING.md:49) still accurate — `app/services/enforcement.py` has only `judge_caption` via `client.system_one`; the `judge_confidence` comment (line 20) mentions "a non-Jev fallback was used" but no such fallback path exists in the code.
- **Test suite**: CONTRIBUTING.md:54 says 3 test files / 15 tests; now 40 files / 422 tests (`test_voice.py`, `test_xpoz.py`, MCP connector, handle-search, profile-extract, provider-fallback, context-budget, turn-class, tool-tiers, coverage-gate, repurpose-endpoint, prompt-5 acceptance suites added).
- **Commit style**: CONTRIBUTING.md:118 prescribes `<verb>: <what>` (e.g. "add: …"), but actual `git log` uses conventional commits (`feat:`, `fix:`, `chore:`, even `fix(agent):`) — e.g. `fab5583 feat: unified monorepo with backend and frontend…`. The docs describe an older convention.
- **`.entire/` "don't commit"**: CONTRIBUTING.md:121 says don't commit anything under `.entire/`, yet `.entire/settings.json` and `.entire/.gitignore` are tracked in git (`git ls-files`).
- **Postgres-only vs SQLite fallback**: every doc says PostgreSQL (README.md:10; setup.md:9,22), but `app/config.py:9` defaults to `sqlite+aiosqlite:///lumi.db` (commit `c820fee chore: enable aiosqlite fallback for local server execution`; `aiosqlite` is in `pyproject.toml`; a local `lumi.db` exists).
- **setup.md spec drift**: lists `create_all` in `database.py` (setup.md:26) which every other doc forbids; plans `eval/captions.json` and `scripts/run_eval.py` (setup.md:71-75) which don't exist; omits `XPOZ_API_KEY` from its env list (setup.md:78-88); lists models files without `listening.py`.
- **frontend-integration.md status table** (lines 110-121) is a frozen snapshot ("verified against the live deployment just now") — `/chat` 500ing on placeholder keys may or may not still be true; treat as time-stamped, not current.
- **docs/background.md:7** still says backfill is "not built yet" — partially outdated given the voice-service PFM fetch.

### 6. Root-level `.agents` and hooks

- **`C:\Users\USER\Downloads\Lumi-agent-backend\.agents\`** exists but is **completely empty** (no files at any depth). All planning specs live in `lumi\.agents\` (tracked: `setup.md`, `api-endpoints.md`, `database.md`, `external-services.md`, `hooks.json`).
- **`lumi/.agents/hooks.json`** (28 lines): Entire project-record tooling hooks targeting an "antigravity" agent CLI. Three events — `PreToolUse` (matcher `*`), `PreInvocation`, `Stop` (300s timeout) — each running a Windows-guarded command: `where.exe entire >nul 2>nul & if errorlevel 1 (ver>nul) else (entire hooks antigravity pre-tool-use)` (and `pre-invocation` / `stop` variants). The `where.exe` guard no-ops if the `entire` CLI isn't installed.
- **`lumi/.claude/settings.json`** (101 lines): Entire hooks for Claude Code — `PostToolUse` (Agent → `post-task`; TaskCreate|TaskUpdate → `post-todo`), `PreToolUse` (Agent → `pre-task`), `SessionStart` (prints an install-guide systemMessage if entire is missing), `SessionEnd`, `Stop`, `StopFailure`, `SubagentStop`, `UserPromptSubmit`. All `sh -c` commands guarded by `command -v entire`.
- **`lumi/.entire/settings.json`**: `{ "enabled": true, "checkpoints": { "primary": { "type": "git-refs" } } }` — explains CONTRIBUTING's "don't touch `entire/*` branches" rule (checkpoint branches are auto-created git refs). `.entire/.gitignore` excludes `tmp/`, `settings.local.json`, `metadata/`, `logs/`, `redactors/local/`.

### 7. package.json / tooling oddities

- **`lumi/package.json`**: named `"lumi-monorepo"` ("FastAPI Backend + React Frontend") with npm scripts delegating both ways — `dev:frontend` (`npm run dev --prefix frontend -- --port 3010`), `build:frontend`, `dev:backend` (`uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`), `lint:backend` (ruff), `test:backend` (pytest). No `workspaces` field despite the monorepo name; no plain `dev` script.
- **Frontend has two lockfiles**: `frontend/package-lock.json` *and* `frontend/pnpm-lock.yaml` both present — mixed npm/pnpm usage, a classic source of divergent installs.
- **`pyproject.toml`**: `name = "lumi"`, `requires-python = ">=3.12"`, `[tool.uv] package = false` (uv-managed, not published), ruff excludes `alembic/versions`, pytest has `asyncio_mode = "auto"` + `pythonpath = ["."]` (so plain `async def test_...` and `from app...` imports work, per CONTRIBUTING.md:54). Deps include both Postgres drivers (`asyncpg`, `psycopg2-binary`) *and* `aiosqlite` — the dual-DB reality the docs don't mention. Notable versions: `openai>=3.28.0`, `neatlogs>=1.4.26`, `typesafe-sdk>=0.7.4`, dev group `pytest>=9.1.1`, `ruff>=0.17.0`.
- **`.gitignore`** ignores `.venv/`, `.env`, `*.db` (so the local `lumi.db` stays untracked), caches, and frontend build artifacts — but **not** `.entire/` or `.claude/` (both are tracked; `.entire/logs/` is excluded only via the nested `.entire/.gitignore`).
- **`alembic/README`** is the generic one-liner stub ("Generic single-database configuration with an async dbapi.") — no project-specific migration guidance beyond CLAUDE.md/CONTRIBUTING.
- **Current git state**: branch `main` (the `ateh` branch this file once described is gone); 205 tracked files; recent history shows aggressive post-hackathon feature growth (trends router, SSE streaming, Xpoz client, analytics, monorepo merge) that none of the docs reflect.

## Next steps: Post for Me from natural language (agreed 2026-10-27)

Goal set by the owner: in the Lumi chat, in plain language, the user can (1) **publish** a post, (2) **read the views** of their posts, and (3) ask **which post is the most viewed**. The work is in the Django backend (`lumi/apps/connections` and `lumi/lumi_ai`); the Post for Me API is the provider for these three. Read `plan/PLAN_REDES-SOCIALES.md` (provider and capability split) and `docs/CONEXIONES.md` first; follow the MANDATORY WORKING PROCESS above (plan first, then code, then docs in the same change).

**What already exists (verified 2026-10-27):**
- Reading: `backfill_posts` runs `DjangoOwnPostSync`; Facebook goes through Meta (R3, stores views only), every other network through Post for Me (`collect_own_posts`, `GET /v1/social-account-feeds/{id}`).
- Publishing: the REST publish flow with `dry_run`, `confirm` and `Idempotency-Key` (`apps/connections/publishing.py`, `publish_api.py`). **The agent has no tool to publish.**
- Agent data tools: `get_posts`, `get_analytics`, `get_user_activity`. There is no tool that ranks posts by views.

**What the Post for Me API offers (read from its OpenAPI spec, `https://api.postforme.dev/docs/json`, v1.0):** `POST /v1/social-posts` (caption, media, `scheduled_at`, `isDraft`, per-network settings), `PUT`/`DELETE /v1/social-posts/{id}`, `GET /v1/social-post-results` (per-network outcome and error), `POST /v1/social-post-previews`, `POST /v1/media/create-upload-url`, `GET /v1/social-account-feeds/{id}?expand=metrics` (posts with metrics), webhooks. Metrics per network: Facebook (reach, media_views, reactions, comments, shares, video metrics), Instagram (likes, comments, views, reach, saved, shares), X (impressions, likes, retweets, replies), LinkedIn (impressions, likes, comments, shares), YouTube (views, likes, minutes watched), TikTok (views, likes, comments, shares). It has **no** comments endpoint, no direct messages, no ads, and no account-level metrics (followers, page reach).

**Steps, in order (one commit per step, tests with the HTTP transport mocked, no live call without the owner's permission):**
1. **Agent tool `publish_post`** (cost `write`, side effects external). Two-step by design: first call runs the existing `dry_run` and returns the preview; the post goes out only after the user confirms in the chat and the tool is called again with `confirm=true` and an idempotency key. The model must never publish on the first message. Add the tool to the right tier in `turn_class.py` (`CLASS_ALLOWED`) and keep the prompt small (Groq free tier: 8,000 tokens per minute).
2. **Route publishing through Post for Me** for the networks Meta/LinkedIn/X do not cover natively, and keep the native provider first where a native connection exists (as `connect_links` does). Create the post with `POST /v1/social-posts`, then read `GET /v1/social-post-results` to report the outcome per network; never report success from the create call alone.
3. **Store more metrics from the feed.** `expand=metrics` already returns likes, comments, shares and views per network; map them into `metric_snapshots` (Facebook currently stores views only through Meta). Missing values stay `NULL`, never `0`.
4. **Agent tool `top_posts`** (read-only): rank the user's stored posts by views (or likes/comments) for a platform and period, return the top N with caption, link and numbers. Answers "which is my most viewed post". The ranking is done in SQL, not by the model.
5. **Natural-language wiring**: make `backfill_posts` refresh automatically when the stored data is older than a set time (or tell the user how old it is), so "how did my posts do?" works without asking to sync first. Add cases to `lumi_ai/tests` golden set for: publish with confirmation, "most viewed post", "views of my last posts", a network with no data yet.
6. **Docs in the same change**: `docs/CONEXIONES.md`, `docs/AI.md` (new tools), `plan/ContextoTareas.md`, `plan/decisions.tsv`, this file's tool list.

**Decisions by the owner (2026-10-27) — these replace the earlier assumptions:**
- **Post for Me is the provider for everything for now: publish, read posts and get metrics, on every network.** The native providers (Meta, LinkedIn, X) stay in the code but are not the route the agent uses in this round. This changes two things already built: R3 (Facebook read through Meta, `own_post_sync.py`) currently wins over Post for Me when a Page is connected, and `connect_links`/`publish_api` put the native provider first; in step 2 the route table must make Post for Me first for these actions, and the change must be logged in `plan/decisions.tsv` as a reversal of that order. Do not delete the native code.
- **Text only** in this round. Photos and videos (media upload endpoint) come later.
- **Publish now only (default; the owner did not ask for more, confirm if that changes).** Scheduling, editing and deleting a published post are not part of this round.
- **There is no Post for Me account or API key yet.** Someone on the team has to create the account and generate the API key (the app-level `PFM_JWT_TOKEN`). Until then nothing can run live: build everything against the mocked HTTP transport (as the existing tests do) and do not ask the owner to paste the key in chat. When the key exists it goes only in `lumi/.env` and in the Railway variables (SECRETS RULE; see `docs/API_KEYS.md`). The owner and the team still have to decide which plan to pay for (Post for Me is a paid service); record that decision in `plan/decisions.tsv`.
- **Blocker before any live test:** the account and key above, the social accounts connected through Post for Me (its `auth-url` flow, not the Meta login), and the owner's explicit permission for the first real publish, on a test account.

**Known blockers that affect this work:** the Groq free-tier limit (8,000 tokens per minute) makes turns with tools fail with 429/413 (the prompt is about 11,700 tokens); slimming it (task A2, needs a golden evaluation) and the per-chat history split (Blocks B and C) are pending. A real publish is an outward-facing action: only with the owner's explicit permission, on a test account.

## Next step: audit which database tables are in use (asked by the owner 2026-10-27)

Goal: check that **every table in the database is actually used**, list the ones that are not, and prepare the endpoints so that the unused data can be worked on later from the interface. This is an audit first; it changes no table and deletes nothing.

**How to do it (plan first, as the MANDATORY WORKING PROCESS says):**
1. **List the tables.** From the Django models (`apps/*/models.py`, `lumi_ai`) and from the live schema (`\dt` on the dev database), so a table that exists in one and not the other also shows up. Keep the list in `docs/` (or `plan/`) as a table: name, app, what it holds.
2. **For each table, find who writes it and who reads it.** Search the code for the model name and the table name: services, repositories (`apps/intelligence/repos`), agent tools (`lumi_ai/tools`), management commands, background jobs, serializers and views. Use `entire graph search` / `entire graph impact` first, as the Entire code graph section says. Record the file and line for each writer and reader.
3. **Classify each table:** used end to end (written and read, reachable from an endpoint or the agent); written but never read (data is collected and nobody shows it); read but never written (nothing fills it); not touched at all (dead or planned).
4. **Check the data too, not only the code.** Count rows per table on the dev database. A table with code but zero rows after normal use is suspect (for example a path that never runs).
5. **Collect the result** in a short report: the list of tables that are not fully used, why, and a proposal per table (add an endpoint, wire it into the agent, fill it from an existing flow, or retire it by the team's decision). Do not drop or migrate anything in this task.
6. **For each table that needs an endpoint,** add it to the backlog with the contract the interface will need (path, method, auth, request and response shape), following `docs/CONTRATOS.md` and the endpoint rules of this file (an agent tool is preferred when the chat can do the job). Implementation of those endpoints is a later task, each one with its own tests.

**Done when:** the report is committed, every table has a line saying used or not used with evidence (file:line and row count), and each unused table has a proposed endpoint or a proposed decision. Known candidates to look at first: tables created for features that are only partly wired (Post for Me posts and metric snapshots beyond views, `chat_conversations` once Block C exists, listening and peer-framework tables, ingest passes, `UserAction` and request tables).

## Project status: what is done and what comes next (snapshot 2026-10-27, branch `lumi-orquestador`)

Same working mode as above: this is a snapshot, add new dated snapshots below it instead of editing old ones. Sources: `git log`, `plan/ContextoTareas.md`, `plan/PLAN_REDES-SOCIALES.md` section 8, `plan/decisions.tsv`. Note: the phase checkboxes in `plan/ContextoTareas.md` (lines ~135-160) are not ticked even though the code for those tasks exists in the branch; trust the code and the test run over those boxes, and tick them when the audit confirms each one.

**Done (verified by running it):**
- **Local run.** Django/DRF + PostgreSQL backend (uvicorn, port 8000) and React/Vite frontend (port 3010) start locally; `/health` is ok. Local Postgres via pgserver; a Docker `postgres:16` also works.
- **Tests.** `apps/connections` and `apps/intelligence`: 1,020 passed, 2 skipped. Known failures that only happen on Windows (subprocess environment, cp1252 encoding, a timer in the SSE test) are left as they are.
- **Handover phases 0-2** from the TRASPASO section: legacy FastAPI moved to `lumi/legacy`, paths repointed, docs and baseline recorded.
- **Agent resilience (Block A of the memory plan).** Short 429s are waited out (`_rate_limit_wait`), the `remember` tool was removed (the background extractor writes memory), `recall_memory` is the only memory tool. Memory across chats works through the rolling summary (checked live with an empty history).
- **Frontend.** Clear English errors in the chat when the agent does not answer (HTML replies, silent or cut stream); selects readable in dark mode.
- **Connections.** Facebook connected through Meta (a Page, not a personal profile; the Page "Sean Labs" is active). CORS now allows the `Idempotency-Key` header so the publish screen can reach the server. The error for a Facebook login with no Pages explains the Page requirement.
- **Credentials policy.** Social-network app credentials live only in `.env` / Railway, documented in `docs/API_KEYS.md` and `docs/CONEXIONES.md`. A database credentials table was built and then reverted on purpose.
- **R3 (Facebook read through Meta).** Posts and views of the 20 newest posts are stored with `source=meta`; tested with a mocked Graph and checked live once (3 posts stored for the Page, views 1, 1 and 2). Likes, comments and shares stay `NULL`.
- **Plans written.** `plan/PLAN_REDES-SOCIALES.md` (provider and capability split) and, in this file, the next steps for Post for Me and the database-table audit.

**Not done / open:**
- **Chat reliability on the Groq free tier.** The system prompt is about 11,700 tokens and the limit is 8,000 tokens per minute, so tool turns fail with 429 or 413 and the context trimmer drops older messages. Task A2 (slim prompt and tools) needs a golden evaluation first.
- **Memory plan Blocks B and C.** B: semantic dedupe of notes (`dedupe_memory`). C: a separate history per chat (`chat_conversations`, `conversation_id`, API, frontend, contract updates).
- **Social network plan.** R0 (decisions with Christian), R1 (revalidate the Meta API against official docs), R2 (single routes table), R4-R8 (publish media, comments, agent tools by action, LinkedIn and YouTube, docs and security review). The owner's decision of 2026-10-27 (Post for Me for everything, text only) changes the order: see the Post for Me section above.
- **Real publish never exercised** by the owner; it needs a test account and explicit permission.
- **Draft PR** `lumi-orquestador` -> `main` is not open; it needs Christian's OK. Nothing is merged to `main`.
- **Blocks needing other people:** a Post for Me account and API key (nobody has created them yet), the App Review / Business Verification of Meta to publish for third parties, Christian's decisions in section 6 of the social plan.

**Recommended order from here:** (1) Post for Me, step 1 `publish_post` tool with preview and confirmation, built against the mocked transport; (2) steps 2-5 of that section; (3) the database-table audit, which is read-only and can run in parallel; (4) A2 and Blocks B-C before any demo, because without them the chat fails under the token limit; (5) tick the stale boxes in `plan/ContextoTareas.md` and open the Draft PR when Christian agrees. One commit per step, tests with the HTTP transport mocked, nothing live without the owner's permission, no force-push, nothing to `main`.

## Entire code graph

The repo has the entire-graph code graph installed (`.entire/graph-agent.md`). For locate/fix/change tasks, prefer:

    entire graph search --repo . --profile full --query "<task in one sentence>"

over raw grep/find, then read the top hit's file around the reported line. Treat graph output as evidence, not an oracle; verify with tests/lint before stopping. If the `entire` CLI isn't installed locally, fall back to normal search — this note is a preference, not a hard dependency.

