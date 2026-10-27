# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Aviso:** este archivo describe el backend FastAPI anterior, que ahora vive en `legacy/`. Los comandos de abajo (`uvicorn app.main:app`, `alembic ...`) se corren desde `legacy/`, ver `legacy/README.md`. La app actual es Django/DRF + PostgreSQL: guía en `docs/how-to-setup.md`, contratos en `docs/CONTRATOS.md` y estado en `plan/ContextoTareas.md` (sección TRASPASO).

## What Lumi is

Chat-based social listening and caption repurpose agent for X (Twitter), built for neatHack (Oct 10–12 2026). A user connects an X account; the agent listens for trending posts and proposes caption rewrites in the user's own voice, delivered through a chat interface. MVP scope is X-only — three seeded demo profiles, no auth, no multi-platform support.

`.agents/*.md` (`setup.md`, `api-endpoints.md`, `database.md`, `external-services.md`) are the planning specs this build follows — treat them as the source of truth over this summary when something doesn't match, and update them in the same change if you deliberately diverge.

## Commands

- Install deps: `uv add <package>` (project uses `uv`, not pip/poetry)
- Run dev server: `uv run alembic upgrade head && uv run uvicorn app.main:app --reload`
- Run tests: `uv run pytest`
- Lint: `uv run ruff check .`
- New migration after editing a model: `uv run alembic revision --autogenerate -m "..."` — **read the generated file before applying it.** Alembic autogenerate has a known gap with SQLModel: it can render `sqlmodel.sql.sqltypes.*` types without importing `sqlmodel`. `alembic/script.py.mako` already forces that import for new migrations, but anything unusual (partial indexes, renamed columns read as drop+add) still needs a manual check.
- Apply migrations: `uv run alembic upgrade head`
- Deploy: `railway up` (Postgres is a separate Railway service in the same project; env vars are set in the Railway dashboard)

## Architecture

Chat-first: a user message goes through the agent loop, which calls tools, which call services. A small REST surface exists only for what the frontend needs outside that loop (listing profiles, loading history, polling alerts) — don't add a new HTTP endpoint for something that could be an agent tool instead; check `.agents/api-endpoints.md` first.

- **`legacy/app/models/`** — SQLModel tables, one file per group (`profile`, `post` [+`MetricSnapshot`], `voice` [`VoiceProfile`+`StyleAnswer`], `repurpose` [`RepurposeRequest`+`RepurposeAttempt`+`UserAction`], `poll`, `chat`). Schema is Alembic-managed (`legacy/alembic/versions/`) — there is no `create_all()` call anywhere; don't add one.
  - `voice_profiles` is **versioned**: each extraction inserts a new row rather than updating in place, and a partial unique index enforces exactly one `is_current=true` row per profile. Any code that writes a new voice profile must flip the old current row to `is_current=False` first, or the insert violates that index.
  - `posts.alerted_at`/`alert_dismissed` implement an alert-once pattern — `check_trending` sets `alerted_at` when a spike is first detected and only re-alerts if the previous alert was dismissed.
- **`legacy/app/routers/`** — thin FastAPI handlers (`chat`, `profiles`, `alerts`). No business logic; delegate to the agent loop or `services/`. `pfm.py` is the exception: `GET /pfm/callback` isn't a frontend endpoint, it's where Post for Me redirects the user's browser after an OAuth connect — see "Connecting an X account" below.
- **`legacy/app/tools/`** — agent-callable functions registered via `@tool(...)` in `legacy/app/tools/registry.py` (name + JSON schema + function). `legacy/app/tools/__init__.py` imports every tool module for its registration side effect — a new tool module must be added there or it never registers.
- **`legacy/app/agent/`** — `loop.py` is the agent loop (send → parse tool calls → execute → repeat, OpenAI-style tool calling); `prompts.py` holds the system prompt; `providers.py` builds the Groq/OpenRouter clients (both OpenAI-compatible, Groq tried first, falls back to OpenRouter on `openai.APIError`) as module-level singletons wrapped once with `neatlogs.wrap()` — don't rebuild clients per-request. The agent loop itself is wrapped in `@neatlogs.span(kind="WORKFLOW")` with `profile_id` bound as session identity via `neatlogs.identify()`, so one chat request is one trace.
- **`legacy/app/services/`** — logic shared across tools and (potentially) routers, independent of the tool-call framing: `pfm.py` (Post for Me client, confirmed against PFM's real OpenAPI spec — `create_auth_url`, `get_social_account`, `get_account_feed`), `metrics.py` (likes/hour velocity + spike detection from `MetricSnapshot` deltas), `enforcement.py` (deterministic must-keep/length checks plus the Jev/TypeSafe AI judge call via `typesafe-sdk`'s `system_one`).
- **`legacy/app/background/poller.py`** — asyncio loop started from the FastAPI `lifespan`, drives `check_trending` for profiles with an active `poll_config` row.
- **`legacy/app/seed.py`** — seeds 3 demo profiles on startup (idempotent by handle); one is deliberately thin on posts to exercise the style-question fallback.

Both the chat-agent path and the HTTP router path reuse the same `services/` layer — tools and routers both stay thin wrappers around it, so logic isn't duplicated between the two entry points.

### Connecting an X account

There's no PFM API key the end user ever sees — `PFM_JWT_TOKEN` is app-level, ours alone. The actual flow is a real OAuth round trip: the `connect_account` tool calls PFM's `auth-url` endpoint and returns a link for the agent to hand the user; the user authorizes on X's own login page; PFM redirects back to `GET /pfm/callback`, which is the *only* place a `Profile` row gets created. `connect_account` itself never touches the database — `pfm_account_id` is `NOT NULL` + unique, so a profile genuinely cannot exist before that redirect lands. Full flow: `.agents/external-services.md`.

## Environment variables

`DATABASE_URL`, `PFM_JWT_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `SECRET_KEY` — copy `.env.example` to `.env` and fill in before running locally. `XPOZ_API_KEY` is also there, optional until social listening via Xpoz is built (see Notes).

## Notes

- The PyPI package for Jev/TypeSafe AI is `typesafe-sdk`, not `typesafe-ai` (`typesafe-ai` is just a redirect shim). Already installed and in use in `legacy/app/services/enforcement.py`.
- Post for Me's docs page (`api.postforme.dev/docs`) is a JS-rendered Scalar UI — if you need the raw OpenAPI spec again, fetch `api.postforme.dev/docs/json` instead (the spec is HTML-entity-encoded inside a `data-configuration` attribute on that page; `.agents/external-services.md` already has the confirmed endpoints extracted from it).
- `backfill_profile_posts` in `legacy/app/services/pfm.py` is the only path from `PFMClient.get_account_feed()` into `posts`/`metric_snapshots` — the `backfill_posts` tool, `extract_voice_profile`, and the poller all call it. Seed profiles have fake `pfm_account_id`s, so it errors for them until real accounts are connected.
- Model IDs for repurpose routing live in `TIER_MODELS` (`legacy/app/agent/providers.py`). Groq has dropped models before — check its `/models` list before changing one.
- **PFM and Xpoz are not interchangeable data sources — don't let anything write Xpoz results into `posts`.** `posts` is PFM-backfilled, `profile_id`-owned (`NOT NULL`), and powers voice extraction only — it means "this profile's own content." Xpoz (social listening) surfaces third-party/market content that informs `repurpose_caption`, not voice extraction, and has its own table for it: `listening_matches` (`legacy/app/models/listening.py`, columns are a scaffold, expect them to change). `XpozClient` (`legacy/app/services/xpoz.py`) exists, and the on-demand `check_niche_trends` tool writes to `listening_matches`; there's no background job for it yet and nothing sets its `alerted_at`. See `CONTRIBUTING.md`'s Tasks list for what's left.
- See `CONTRIBUTING.md` for the day-to-day workflow (git conventions, where to add new tools/models/endpoints) — this file is architecture orientation, not process.

<!-- entire-graph:begin -->
This repo has the entire-graph code graph installed. Before exploring code with
grep/find/whole-file reads, read .entire/graph-agent.md — resolution-first guidance
for using graph retrieval, focused source inspection, and verification.
@.entire/graph-agent.md
<!-- entire-graph:end -->
