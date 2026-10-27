# Lumi

Chat-based agent that listens for trending X posts and repurposes captions in the user's voice.

MVP scope: **X (Twitter) only**. All demo profiles are X accounts, and repurposed output targets X's 280-character format. Multi-platform support is a future extension, not an MVP goal.

## Stack

- **API:** Python 3.12, FastAPI
- **Data:** SQLModel (SQLAlchemy 2.0) on PostgreSQL, Alembic for migrations, hosted on Railway
- **LLM:** Groq (primary) with OpenRouter (fallback) via the OpenAI Python SDK
- **Judge:** Jev / TypeSafe AI (`typesafe-sdk`) for must-keep/meaning-preservation verdicts
- **Social data:** Post for Me (account linking, post backfill, metrics)
- **Observability:** neatlogs (traces every LLM call and the agent loop)
- **Tooling:** `uv` for deps/venv, `ruff` for lint, `pytest` for tests
- **Project record:** Entire

## Architecture

The interface is chat-based. A user talks to the agent; the agent calls tools; tools call services; services talk to the database and external APIs. A small set of REST endpoints exists only for what the frontend needs directly (listing profiles, loading chat history, polling alerts) — everything else happens inside the agent loop, not as a direct HTTP call.

```
routers/          thin HTTP handlers — chat, profiles, alerts
   |
agent/loop.py      send -> parse tool calls -> execute -> repeat (OpenAI-style tool calling)
   |
tools/             agent-callable functions, registered by name + JSON schema in tools/registry.py
   |
services/          business logic shared across tools (PFM client, metrics/velocity, enforcement)
   |
models/            SQLModel table definitions, one file per table group
```

Both the chat agent path and the HTTP router path reuse the same `services/` layer — tools stay thin wrappers around it, mirroring how routers stay thin wrappers too, so logic isn't duplicated between the two entry points.

### Directory layout

```
app/
├── main.py              FastAPI app, lifespan (seed + background poller), CORS
├── config.py            Settings from env vars (pydantic-settings)
├── database.py          Async engine/session; schema is Alembic-managed, not create_all()
├── seed.py              Seeds 3 demo profiles on startup
│
├── models/              SQLModel tables — see "Database" below
├── routers/             chat.py, profiles.py, alerts.py, pfm.py (PFM's OAuth callback, not a frontend endpoint)
├── tools/               agent-callable functions + registry.py (name -> function + JSON schema)
├── agent/               loop.py (the agentic loop), prompts.py, providers.py (Groq/OpenRouter + neatlogs)
├── services/            pfm.py, metrics.py, enforcement.py
└── background/          poller.py — asyncio loop started from lifespan, drives check_trending

alembic/                 migrations (async template, autogenerate against SQLModel.metadata)
.agents/                 the planning specs this build follows (setup, API, database, external services)
```

### Database

11 tables, defined in `app/models/` and managed by Alembic (`alembic/versions/`):

| Table | Purpose |
|---|---|
| `profiles` | Seeded/connected X accounts. `pfm_account_id` is unique + required — a profile only exists once it's linked. |
| `posts` | Backfilled from Post for Me. **The profile's own content only.** `alerted_at`/`alert_dismissed` drive the alert-once pattern. Unique on `(profile_id, platform_post_id)`. |
| `metric_snapshots` | Append-only engagement snapshots; velocity is computed from deltas between rows. Unique on `(post_id, captured_at)`, indexed `(post_id, captured_at DESC)`. |
| `listening_matches` | Social listening results from Xpoz — **not** the profile's own content; `profile_id` means "whose tracked niche this matched," not "who posted it." Feeds `repurpose_caption` as a `source_text` candidate. Same alert-once pattern as `posts`. Not yet populated by anything (no ingestion pipeline built). |
| `voice_profiles` | **Versioned.** Each extraction adds a new row; a partial unique index enforces exactly one `is_current=true` row per profile. `payload` (JSON) holds tone/vocabulary/structure; `example_post_ids` (JSON) holds 5–10 source post IDs. |
| `style_answers` | Fallback style questions, used when a profile has too few posts to extract a voice from. |
| `repurpose_requests` | One per caption submitted for repurposing. `source_caption` plus an optional `route_label` (easy/standard/hard). |
| `repurpose_attempts` | One per generation attempt. `must_keep_passed` is the deterministic gate (length + must-keep phrases); `judge_verdict`/`judge_confidence` come from the Jev judge, independently. `tier`/`model`/`provider`/`attempt_no` capture retry/fallback history once the real generation pipeline lands. |
| `user_actions` | Append-only log of accept/edit/reject per attempt. |
| `poll_config` | Per-profile background polling config — `interval_minutes`, `is_active`, `last_polled_at`. |
| `chat_messages` | Full conversation history, including a `tool_calls` JSON column for the raw tool-call array on assistant turns. |

Full column-level spec: `.agents/database.md`.

### Agent tools

Registered in `app/tools/registry.py`, callable by the LLM during the chat loop:

`connect_account`, `extract_voice_profile`, `get_voice_profile`, `answer_style_questions`, `start_listening`, `stop_listening`, `check_trending`, `repurpose_caption`, `submit_action`, `dismiss_alert`, `get_posts`, plus **dynamic MCP connector tools** (`mcp__gdrive__*`, `mcp__gdocs__*`) — discovered per-turn from the connector registry when Google is connected, with every write gated behind explicit user confirmation (see "External services" and `docs/mcp-connectors.md`).

### API endpoints

Only what the frontend needs outside the chat loop. Full request/response shapes: `.agents/api-endpoints.md`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat` | Agent loop entry point — returns `{role, content, tool_calls_made}` |
| `GET` | `/chat/history` | Paginated conversation history for a profile |
| `GET` | `/profiles` | List profiles for the profile switcher |
| `POST` | `/profiles/{id}/select` | UI-level "make this the active profile" — returns voice/post/listening state |
| `GET` | `/profiles/{id}/alerts/unread` | Posts with undismissed spike alerts; frontend polls this every 5–10s |

`GET /pfm/callback` also exists, but it's not for the frontend — see "External services" below. The three Google OAuth routes for MCP connectors (`GET /mcp/google/connect|callback|status`) are the same kind of flow — see `docs/mcp-connectors.md`.

### External services

Details, rate limits, and model choices: `.agents/external-services.md`.

- **Post for Me** — account connection is a real OAuth flow, not an API key the user provides. `connect_account` (an agent tool) calls PFM's `auth-url` endpoint and hands the user a link; PFM redirects back to `GET /pfm/callback` once they've authorized, which is where a `Profile` row actually gets created. Auth to PFM itself is one app-level JWT (`PFM_JWT_TOKEN`) — PFM holds the real platform tokens, we only ever store `pfm_account_id`. Post backfill and metrics both come from one endpoint (`GET /v1/social-account-feeds/{id}`), confirmed but not yet wired into any backfill/polling pipeline.
- **Xpoz** — social listening (not yet integrated — tracked keywords/users/content across X broadly, not just our connected accounts). Different purpose from PFM: PFM only ever sees accounts a user has OAuth-connected; Xpoz reads public content generally, which is what "listen for trending posts in the niche" actually needs. See `.agents/external-services.md` for the confirmed endpoints and an open schema question (posts surfaced this way don't belong to any `profile_id`) that needs a decision before building.
- **Groq** (primary) / **OpenRouter** (fallback) — both OpenAI-compatible, both go through `app/agent/providers.py` via the OpenAI SDK with a `base_url` override. Groq is tried first; any `openai.APIError` falls back to OpenRouter.
- **Jev / TypeSafe AI** — the must-keep/meaning-preservation judge, called from `app/services/enforcement.py` via `typesafe-sdk`'s `system_one` API.
- **neatlogs** — wraps both provider clients and the agent loop (`@neatlogs.span(kind="WORKFLOW")`) so every chat request shows up as one trace with its nested LLM calls grouped underneath.
- **Google (MCP connectors)** — Drive/Docs via Google's official MCP servers, called by Lumi's own in-backend MCP client (`mcp` SDK, Streamable HTTP) with a per-user OAuth token we obtain, store (`mcp_auth_accounts`), and refresh. Connector tools ride the same Groq tool-calling loop; writes require explicit user confirmation. Setup checklist + "add another connector" recipe: `docs/mcp-connectors.md`.

## Environment variables

```
DATABASE_URL         postgresql+asyncpg://... (Railway Postgres)
PFM_JWT_TOKEN        Post for Me, app-level JWT
XPOZ_API_KEY         Xpoz, social listening (optional until that integration lands)
GROQ_API_KEY         Groq, primary LLM provider
OPENROUTER_API_KEY   OpenRouter, fallback LLM provider
TYPESAFE_API_KEY     Jev / TypeSafe AI judge
NEATLOGS_API_KEY     neatlogs tracing
SECRET_KEY           App secret (signing)
GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET   Google OAuth web client for the MCP connectors (optional; see docs/mcp-connectors.md)
GOOGLE_OAUTH_REDIRECT_URI   default http://localhost:8000/mcp/google/callback
MCP_ENABLED / MCP_GDRIVE_ENABLED / MCP_GDOCS_ENABLED   connector switches (default true)
```

## How to run

```
cp .env.example .env   # fill in the keys
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Migrations

Schema changes go through Alembic, not `SQLModel.metadata.create_all`.

```
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

## How to deploy

Live at `https://lumi-api-production-6260.up.railway.app` (service `lumi-api` in the `lumi` Railway project, alongside `Postgres`).

```
railway up --service lumi-api
```

**Always pass `--service` explicitly** — the first deploy attempt went to the existing Postgres service instead of creating a new one, because no service was specified and a project was already linked.

`railway.json` documents the intended start/pre-deploy/healthcheck commands, but **Railway silently ignored it on this service** (prints a Config-as-Code deprecation warning, doesn't apply the file). The actual config was set directly via the Railway service settings. If `railway.json` stops being honored at all, or you're setting up a new service, configure these directly instead:
- Start command: `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Pre-deploy command: `uv run alembic upgrade head`
- Healthcheck path: `/health`

Postgres runs as its own Railway service. Environment variables are set in the Railway dashboard.

## Demo profiles

Three seeded X accounts are created on startup. One is deliberately thin on post history, to exercise the style-question fallback path when there isn't enough content to extract a voice profile from.

## Hackathon

neatHack, Oct 10–12 2026. Submission as a quote post on X with the repo link and a 3-minute demo.
