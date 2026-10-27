# Contributing to Lumi

Quick orientation for the team. For architecture, the database schema, and the API surface, read [README.md](README.md) first — this file is about how we work in the repo day to day.

## Setup

```
git clone <repo>
cd lumi
uv sync
cp .env.example .env
```

Fill in `.env`:
- `DATABASE_URL` — ask in the team channel for the Railway Postgres connection string (public proxy host:port + password), or provision your own via `railway add --database postgres` if you want an isolated DB for local work.
- `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `PFM_JWT_TOKEN` — ask for these; don't request new ones per-person unless a shared key runs out of quota.
- `XPOZ_API_KEY` — optional for now; only needed once you're working on social listening.
- `SECRET_KEY` — any random string for local dev.

Then:

```
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Visit `http://localhost:8000/docs` for the live OpenAPI schema.

**Before you touch anything else: create your own branch.** Nobody commits to `main` directly — see "Git workflow" below for the full process (branch → checks pass → PR → merge).

## Tasks

Next steps to get this from "runs locally" to an actual live product. Open items first, then what's done.

### Handed off — needs dashboard/account access

These are blocked on access to external dashboards, not on code. Handed off to a teammate; the code side is already in place for all of them.

- [ ] **Register the Post for Me callback URL.** The OAuth connect flow is implemented (`connect_account` → `GET /pfm/callback`), but Post for Me redirects to whatever URL is configured in *their* project dashboard — it can't be set via the API with system credentials. Someone with PFM dashboard access needs to point it at `https://lumi-api-production-6260.up.railway.app/pfm/callback`.
- [ ] **Replace placeholder seed data with real accounts.** `app/seed.py`'s three demo profiles have fake `pfm_account_id` values (`demo-pfm-creator`, etc.) and zero posts. Once the callback is registered, run `connect_account` for three real X accounts through the chat — keep one deliberately low-post-count to exercise the style-question fallback — then run `backfill_posts` for each. Until this is done, the poller logs a PFM error for the seed profiles every tick, and calling `backfill_posts` on one returns an error to the agent.
  - **Possible shortcut, untested:** PFM may create the social account on its side even if the redirect lands somewhere wrong. If any X accounts are already connected in our PFM project, their real IDs could be copied straight into `seed.py` without waiting on the callback.
- [ ] **Get real keys into the Railway dashboard** (`lumi-api` service). `GROQ_API_KEY`/`OPENROUTER_API_KEY` were placeholders on the live deploy, which is why `POST /chat` 500s there. Also confirm `TYPESAFE_API_KEY` (Jev), `NEATLOGS_API_KEY` (traces actually land), `PFM_JWT_TOKEN`, and `XPOZ_API_KEY` are set.

### Open

- [ ] **Finish wiring Xpoz social listening into the background flow.** Built so far: `XpozClient` (`app/services/xpoz.py`), and the on-demand `check_niche_trends` tool, which fetches tweets for a list of handles and writes the ones above `min_likes` into `listening_matches` (deduped by `platform_post_id`). Still missing:
  - somewhere to store which handles a profile listens to (handles are currently passed in on every call)
  - a poller step that runs it on a schedule, like `check_trending` does for `posts`
  - `GET /profiles/{id}/alerts/unread` surfacing `listening_matches` — nothing sets their `alerted_at` yet
  - note: `discover_and_extract_niche_frameworks` uses Xpoz keyword search (`search_live_posts`), which `.agents/external-services.md` originally chose to skip — update that spec or the tool so they agree
- [ ] **Retry one tier up when the judge rejects a rewrite.** `.agents/external-services.md` specs retrying a rejected or low-confidence rewrite on the large model. `repurpose_caption` currently makes exactly one attempt (`attempt_no` is always 1).
- [ ] **Route the judge fallback through `app/agent/providers.py`.** `_judge_llm_fallback` in `app/services/enforcement.py` builds its own `AsyncOpenAI` client, so that LLM call isn't traced by neatlogs and doesn't fall back to OpenRouter (see `docs/agent.md`). `chat_completion_with_provider(..., model=TIER_MODELS["small"])` already does both.
- [ ] **Add tests for the DB-dependent foundations — needs a real Postgres, so held back from the first pass:**
  - the `voice_profiles` version-flip (old row → `is_current=False` + flush, before the new current row is inserted) — the partial unique index means getting the order wrong fails loudly, but it's still worth locking down
  - the `posts` alert-once behavior (`check_trending` re-alerting only after dismissal, not every tick)
  - `backfill_profile_posts` dedup (re-running it adds snapshots, never duplicate posts)
  - the agent loop's tool-calling cycle and its `MAX_TOOL_ITERATIONS` cutoff — needs a fake/mocked provider response (no real Groq call required) but still touches `session_scope()` for every message, so needs a DB connection or heavy mocking of it
- [ ] **Wire up the frontend through `/chat` — keep it simple.** Almost everything should go through `POST /chat` (or `POST /chat/stream` for live tool progress); `/profiles`, `/profiles/{id}/select`, and `/profiles/{id}/alerts/unread` exist only for UI state the chat loop doesn't cover. If the frontend needs something new, that's almost always a reason to add an agent tool, not a new endpoint — resist the urge to grow the REST surface.

### Done

- [x] ~~Populate the tools that still stubbed their logic.~~ `extract_voice_profile` calls the LLM (`app/services/voice.py`) and `repurpose_caption` produces real platform-specific rewrites (`app/services/repurpose.py`).
- [x] ~~Build the backfill/polling pipeline on top of `get_account_feed`.~~ `backfill_profile_posts` in `app/services/pfm.py` pages through the feed, upserts `posts` (deduped by `platform_post_id`, skipping retweets and replies), and appends a fresh `MetricSnapshot` per post on every run. Called from the `backfill_posts` tool, from `extract_voice_profile` when a profile has too few posts, and by the poller before every spike check. A PFM 429 stops the run and it picks up next tick.
- [x] ~~Revisit the alerting logic.~~ `detect_spike` is now relative: a post spikes when its current likes/hour is at least 3× its own baseline, with a floor of 5 likes/hour so near-zero posts don't trigger. Repurposing an alerted post auto-dismisses its alert.
- [x] ~~Add the Jev-unavailable fallback.~~ The judge degrades Jev → small model on Groq (`gpt-oss-20b`) → deterministic checks only, with the caption flagged for manual review. `EnforcementResult.judge_source` records which one answered.
- [x] ~~Set `repurpose_requests.route_label`.~~ Jev classifies each request easy/standard/hard (rule-based fallback if Jev errors). The label picks the rewrite model: easy → `gpt-oss-20b`, standard/hard → `gpt-oss-120b`. Attempts now record `tier`, `model`, `provider`, and `platform`.
- [x] ~~Deploy the app itself, not just the database.~~ Live at `https://lumi-api-production-6260.up.railway.app` (service: `lumi-api`, same `lumi` Railway project as Postgres). Full endpoint docs: `docs/frontend-integration.md`.
  - **Gotcha for next time a service is deployed fresh:** `railway.json`'s `startCommand`/`preDeployCommand`/`healthcheckPath` were **silently ignored** on this brand-new service — Railway printed a Config-as-Code deprecation warning but didn't actually apply the file. Had to set `startCommand`/`preDeployCommand`/`healthcheckPath` directly via the Railway service settings (dashboard, or `update-service` through the MCP/API) instead. Keep `railway.json` around as documentation of intent, but don't assume it's actually being read — verify a fresh deploy's build logs for "No start command detected" before trusting it.
  - **Near-miss worth remembering:** the very first deploy attempt went to the *existing* Postgres service instead of creating a new one, because no `--service` flag was given and a project was already linked. **Always pass `--service <name>` explicitly** (or create the service first with `railway add --service <name>`) rather than relying on default resolution.
- [x] ~~Add tests for core functionality.~~ 34 tests across `tests/`, all pure/mocked — no DB, no `.env`, no API keys required; run with `uv run pytest`. `asyncio_mode = "auto"` and `pythonpath = ["."]` are set in `pyproject.toml` so plain `async def test_...` functions and `from app...` imports both just work.

## Where things live

- **New agent tool** → add a function in `app/tools/`, decorate it with `@tool(name=..., description=..., parameters=<JSON schema>)` from `app/tools/registry.py`, and import the module from `app/tools/__init__.py`. Keep the function itself thin — push any real logic into `app/services/` so routers could reuse it too.
- **New DB table/column** → edit the SQLModel class in `app/models/`, then see "Database changes" below.
- **New HTTP endpoint** → only add one if the frontend needs it directly outside the chat flow. Check `.agents/api-endpoints.md` first — most functionality should be an agent tool, not a route.
- **Shared business logic** (not agent- or HTTP-specific) → `app/services/`.

## Database changes

Schema is Alembic-managed. Never add ad-hoc `create_all()` calls or hand-edit the production DB.

1. Edit the SQLModel class(es) in `app/models/`.
2. Generate the migration against a real (can be empty) Postgres instance — autogenerate needs a live DB to diff against:
   ```
   uv run alembic revision --autogenerate -m "describe the change"
   ```
3. **Read the generated file in `alembic/versions/` before running it.** Alembic autogenerate has a known gap with SQLModel: it sometimes renders `sqlmodel.sql.sqltypes.*` types without importing `sqlmodel` — our `script.py.mako` template now always includes `import sqlmodel`, but double-check anything unusual (partial indexes, enum changes, column renames autogenerate reads as drop+add).
4. Apply it locally and confirm it works: `uv run alembic upgrade head`.
5. Commit the model change and the migration file together in the same commit/PR — a model change without its migration (or vice versa) breaks the next person's `alembic upgrade head`.

## Conventions

- Lint before you commit: `uv run ruff check .`. CI (if/when we add it) will enforce this; don't make a teammate find your lint errors.
- Everything in `app/` is async — routes, tools, services, DB sessions. Use `session_scope()` from `app/database.py` for DB access outside of FastAPI's request lifecycle (tools, background jobs); use the `get_session` dependency inside routers.
- No comments explaining *what* code does — names should carry that. A short comment is fine for a non-obvious *why* (a workaround, a constraint from an external API, a TODO pointing at unfinished integration work).
- Don't add abstractions, config flags, or error handling for cases that can't happen yet. Match the existing MVP scope (X/Twitter only, 3 demo profiles, no auth) rather than building ahead of it.
- If you leave something intentionally unfinished (a stub, a placeholder value), mark it `# TODO: ...` with enough context for someone else to pick up — see `app/seed.py` for an example already in the codebase.

## Git workflow

**Nobody commits to `main` directly — not even a one-line fix.** Every change goes: your own branch → checks pass locally → PR → merge.

1. **Branch off `main`.** Name it whatever's clear — `<yourname>/<short-description>` or `<area>/<short-description>` both work (`gbemike/pfm-backfill`, `listening/xpoz-client`). There's no enforced convention, just don't commit straight to `main`.
2. **Make your change.**
3. **Before opening a PR, all of these must pass locally:**
   ```
   uv run ruff check .
   uv run pytest
   ```
   Both are fast (lint is instant, the test suite runs in a few seconds) — there's no excuse to skip this. If you added something that genuinely can't be unit tested yet (needs a real DB, real API keys), say so in the PR description rather than silently skipping verification.
4. **Before opening a PR, also smoke-test the exact production start command** — this catches import errors, missing dependencies, and startup crashes that `pytest` alone won't, since it's the literal command Railway runs:
   ```
   export PORT=8080
   uv run alembic upgrade head
   uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
   # in another terminal:
   curl http://localhost:8080/health   # expect {"status":"ok"}
   ```
   If this doesn't boot cleanly and pass its own healthcheck locally, it won't pass Railway's healthcheck either — the deploy will fail the exact same way in production. Catch it here, not after merging.
5. **Open the PR into `main`.** Describe what changed and confirm in the description that steps 3–4 passed. Get it reviewed before merging — don't merge your own PR without at least a look from someone else if you can avoid it.
6. **After merging**, whoever has Railway access redeploys: `railway up --service lumi-api` from `main`, then confirms the live healthcheck:
   ```
   curl https://lumi-api-production-6260.up.railway.app/health
   ```
   If step 4 passed locally, this should be a non-event. If it isn't, something differs between local and Railway's environment (env vars are the usual culprit) — check the deploy logs before assuming the code is at fault.

**Other rules:**
- Commit messages follow `<verb>: <what>` — look at `git log` for examples (`add: chat, profiles, and alerts routers`, `fix: profile.name regression in select_profile`). Use `fix:`/`update:` where appropriate.
- Don't force-push `main`.
- **Don't touch `entire/*` branches.** They're auto-created checkpoint branches from the Entire project-record tooling, not feature branches — leave them alone.
- Don't commit `.env` (it's gitignored) or anything under `.entire/`.

**Not set up yet, worth it if the team grows or the timeline allows:** there's no CI running these checks automatically, and no separate Railway staging environment to deploy a branch to before it touches production — right now "deploy safety" means the local smoke test in step 4, not an isolated real deploy. If that's not enough rigor later, the next step up is a second Railway environment (`railway environment new staging` or via the dashboard) to deploy branches into before merging, rather than trusting the local check alone.

## Specs

The `.agents/` directory holds the planning docs this build follows — treat them as the source of truth when a question comes up about expected behavior, not just this codebase as it currently stands:
- `setup.md` — overall project scope and directory plan
- `api-endpoints.md` — exact request/response shapes for the HTTP surface
- `database.md` — column-level schema for every table
- `external-services.md` — Post for Me, Groq, OpenRouter, Jev/TypeSafe AI, neatlogs: auth, rate limits, confirmed endpoints, and the real OAuth connect flow (confirmed against PFM's actual OpenAPI spec at `api.postforme.dev/docs/json`)

If you change something that contradicts one of these docs on purpose, update the doc in the same PR so it doesn't go stale.
