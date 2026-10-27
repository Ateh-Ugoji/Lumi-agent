# Project Setup

## Scope

Lumi MVP — chat-based social listening and caption repurpose agent for X (Twitter). FastAPI backend, PostgreSQL on Railway, deployed via `railway up`. Repo lives on Entire.

## Dependencies

**Core:** fastapi, uvicorn[standard], sqlmodel, asyncpg, psycopg2-binary

**LLM + external services:** openai, httpx, pydantic, typesafe-ai

**Observability:** neatlogs

**Dev:** ruff, pytest, pytest-asyncio

Install all with `uv add`. Check the `typesafe-ai` package name against their docs — early access packages may differ.

## Directory Structure

```
app/
├── __init__.py
├── main.py                  # FastAPI app, lifespan, CORS
├── config.py                # Settings from env vars via pydantic BaseSettings
├── database.py              # Engine, session, create_all
│
├── models/                  # SQLModel table definitions
│   ├── __init__.py
│   ├── profile.py           # Profile
│   ├── post.py              # Post, MetricSnapshot
│   ├── voice.py             # VoiceProfile, StyleAnswer
│   ├── repurpose.py         # RepurposeRequest, RepurposeAttempt, UserAction
│   ├── poll.py              # PollConfig
│   └── chat.py              # ChatMessage
│
├── routers/                 # FastAPI route handlers
│   ├── __init__.py
│   ├── chat.py              # POST /chat, GET /chat/history
│   ├── profiles.py          # GET /profiles, POST /profiles/{id}/select
│   └── alerts.py            # GET /profiles/{id}/alerts/unread
│
├── tools/                   # Agent tool functions
│   ├── __init__.py
│   ├── registry.py          # Tool registry — maps names to functions and schemas
│   ├── connect.py           # connect_account
│   ├── voice.py             # extract_voice_profile, get_voice_profile, answer_style_questions
│   ├── listening.py         # start_listening, stop_listening, check_trending
│   ├── repurpose.py         # repurpose_caption
│   ├── actions.py           # submit_action, dismiss_alert
│   └── posts.py             # get_posts
│
├── agent/                   # Agent loop and LLM interaction
│   ├── __init__.py
│   ├── loop.py              # While loop: send → parse tool calls → execute → repeat
│   ├── prompts.py           # System prompt templates
│   └── providers.py         # Groq, OpenRouter, Jev client setup and fallback logic
│
├── services/                # Business logic shared across tools
│   ├── __init__.py
│   ├── pfm.py               # Post for Me API client (httpx)
│   ├── metrics.py           # Velocity computation, spike detection
│   └── enforcement.py       # Character limits, must-keep check, Jev judge call
│
├── background/              # Background polling
│   ├── __init__.py
│   └── poller.py            # asyncio loop started in lifespan
│
└── seed.py                  # Seed 3 demo profiles on startup

eval/
└── captions.json            # ~20 real captions with must-keep annotations

scripts/
└── run_eval.py              # Run eval set, log results to neatlogs
```

## Environment Variables

```
DATABASE_URL
PFM_JWT_TOKEN
GROQ_API_KEY
OPENROUTER_API_KEY
TYPESAFE_API_KEY
NEATLOGS_API_KEY
SECRET_KEY
```

## README

The README should cover:

- **What Lumi is:** one sentence. Chat-based agent that listens for trending X posts and repurposes captions in the user's voice.
- **Stack:** Python 3.12, FastAPI, SQLModel, PostgreSQL, Groq, OpenRouter, Jev (TypeSafe AI), neatlogs, Entire.
- **How to run:** copy `.env.example` to `.env`, fill in keys, `uv run uvicorn app.main:app`.
- **How to deploy:** `railway up`. Postgres is Railway's plugin. Env vars set in Railway dashboard.
- **Demo profiles:** three seeded X accounts. One deliberately thin to show the style-question fallback.
- **Hackathon:** neatHack Oct 10–12 2026. Submission as a quote post on X with repo link and 3-minute demo.