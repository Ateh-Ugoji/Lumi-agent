# How to set up Lumi locally

Everything you need to go from `git clone` to a working app. Read this before [`../README.md`](../README.md) — the README covers architecture and deployment, this covers your machine.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | latest | Python deps + venv (`.python-version` pins **3.12**; uv installs it for you) |
| Node.js | 20+ | frontend (Vite 8 / React) |
| npm | bundled with Node | `npm install` / `npm run dev` |
| git | any | clone |

No Docker, no local Postgres: local dev uses **SQLite** (`lumi.db`) by default.

## 1. Clone

```bash
git clone https://github.com/Ateh-Ugoji/Lumi-agent hackathon
cd hackathon/lumi          # backend + docs live here
```

## 2. Environment file

```bash
cp .env.example .env
```

Fill in at minimum the **required** keys — the app refuses to boot without them (`app/config.py`):

| Required | What it is |
|---|---|
| `GROQ_API_KEY` | primary LLM provider |
| `OPENROUTER_API_KEY` | fallback LLM provider |
| `TYPESAFE_API_KEY` | Jev / TypeSafe judge |
| `NEATLOGS_API_KEY` | tracing (a placeholder value boots fine, tracing just no-ops) |
| `SECRET_KEY` | app signing secret — any long random string is fine locally |

Everything else is optional and has a sensible default:

| Optional | Default when unset |
|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///lumi.db` (local SQLite — leave it) |
| `PFM_JWT_TOKEN` | empty — own-post ingest/backfill/voice extraction stay parked |
| `XPOZ_API_KEY` | empty — social listening degrades, everything else works |
| `OPENLUX_API_KEY` / `OPENLUX_MODEL` | third provider, skipped when unset |
| `CHROMA_API_KEY` / `CHROMA_TENANT` / `CHROMA_DATABASE` | falls back to a **local** `.chroma` folder |
| `GOOGLE_OAUTH_CLIENT_ID` / `..._SECRET` / `MCP_ENABLED` | Google connectors off (honest 503) |

**Never commit `.env`** — it is gitignored, and so are `*.db`, `.venv/`, `node_modules/`, `__pycache__/`, `*.log`, `memory.md`. Share keys with teammates over a password manager or DM, not in the repo.

## 3. Backend

```bash
uv sync                      # install Python deps into .venv
uv run alembic upgrade head  # create/migrate the SQLite DB (21 tables)
uv run uvicorn app.main:app --reload
```

Backend is up at **http://127.0.0.1:8000** when `GET /health` returns JSON.

> **First boot takes 60–90 seconds.** The lifespan seeds profiles, connects Chroma and backfills the framework index before it starts accepting requests. That's expected, not a hang.

Useful checks:

```bash
uv run ruff check .   # lint — should be clean
uv run pytest -q      # test suite
curl http://127.0.0.1:8000/health
```

## 4. Frontend

Second terminal:

```bash
cd hackathon/lumi/frontend
npm install
npm run dev
```

UI is at **http://localhost:3010** (port is pinned in `vite.config.ts`). It calls `http://localhost:8000` by default; point it elsewhere with `VITE_API_BASE` if your backend lives on another host.

Frontend scripts: `npm run dev` · `npm run build` · `npm run typecheck` · `npm test` (node's built-in runner).

## 5. Verify the loop

1. Open http://localhost:3010 — the app loads with seeded profiles.
2. `curl http://127.0.0.1:8000/profiles` returns the same profiles.
3. Send a chat message; the reply streams back over SSE.

## Data: fresh vs. seeded

A fresh clone starts with an **empty** database (migrated, 0 profiles — the seed keeps only user accounts). Two options:

- **Clean slate (default):** just run the migrations above.
- **Real data to test against:** copy the `lumi.db` from whoever has the populated one, *after* `alembic upgrade head`, then restart the backend. The file is gitignored on purpose — move it over a shared drive/DM, never through git.

## Migrations (when the schema changes)

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

Alembic only — `SQLModel.metadata.create_all` is never used. Run `uv run alembic check` before committing a migration; it catches drift autogenerate would silently "fix" by dropping an index.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Backend sits at "Waiting for application startup" for a minute | Chroma framework backfill in the lifespan — wait, it completes |
| `neatlogs wrapper: no TracerProvider…` warning | `NEATLOGS_API_KEY` missing/empty — harmless, spans just aren't exported |
| `Address already in use` on 8000/3010 | another copy is running — `netstat -ano \| findstr :8000`, kill that PID |
| Frontend can't reach the API | backend not up yet, or `VITE_API_BASE` points somewhere else |
| Validation error at import listing `groq_api_key…` | `.env` missing or a required key is blank — see step 2 |
| `repository not found` on clone | you're on the old repo URL; the current one is `Ateh-Ugoji/Lumi-agent` |

## Where things live

```
lumi/
├── app/            # FastAPI backend — routers/, services/, agent/, analysis/, models/
├── alembic/        # migrations (versions/ = the schema history)
├── frontend/       # React + Vite UI
├── tests/          # pytest suite
├── docs/           # this file, flow maps, per-module notes (docs/README.md = index)
├── .agents/        # planning specs the build follows
├── AGENTS.md       # architecture source of truth for humans AND agents
└── .env.example    # env template — copy to .env
```
