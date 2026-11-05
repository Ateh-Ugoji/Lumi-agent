# Lumi Backend

Backend service for Lumi: a social media intelligence agent that learns creator voice profiles, extracts winning competitor frameworks, and repoints high-performing hooks across platforms.

---

## 1. Stack & Architecture

- **Framework**: Django 5.2+ (ASGI via `uvicorn`) with Django REST Framework.
- **AI Engine (`lumi_ai/`)**:
  - LLM Provider Chain: Groq (primary), OpenRouter (fallback), OpenLux.
  - Evaluation & Guardrails: Jev / TypeSafe AI SDK (`system_one`) for meaning preservation and deterministic quality checks.
  - Retrieval & Vectors: ChromaDB with ONNX MiniLM local embeddings.
  - Style Learning: `StyleService` (frequency-based sampling, reply style extraction, versioned `VoiceProfile` rows).
  - Competitor Analysis: Outlier detection ($\ge 1.5\times$ median), blind tagging, lift-table synthesis.
- **Connections & Social Data**:
  - Post for Me (PFM): Account linking, OAuth callbacks, profile avatar synchronization, publishing.
  - Xpoz: Real-time multi-platform social search and listening.
- **Database**: PostgreSQL 16.
- **Job Engine**: `apps.core.jobs` (runs eager inline in development and via workers in production).

---

## 2. Directory Structure

```
lumi/
├── apps/
│   ├── accounts/         # User auth, API tokens (Token/Bearer support)
│   ├── connections/      # PFM integration, OAuth state, connected_accounts, MCP
│   ├── core/             # Background jobs engine, error handling, env parsing
│   ├── intelligence/     # AI tasks (bootstrap, refresh), niche preferences, reports
│   └── profiles/         # Social handles, profiles, posts, metric snapshots
├── config/               # Settings (base.py, dev.py, test.py, prod.py), asgi.py
├── frontend/             # React SPA, Vite, Tailwind CSS
├── lumi_ai/              # Agent loop, tool registry, generation, competitor pipeline
├── scripts/              # Dev scripts (dev_postgres.py, seed utilities)
└── docs/                 # System documentation, contracts, schemas, flow maps
```

---

## 3. Core Intelligence Features

### A. Automatic Profile Bootstrap (`profile.bootstrap`)
Whenever an account connects or links via PFM, a `profile.bootstrap` job is queued:
1. **Sync Posts**: Pulls recent posts and metrics into `posts` and `metric_snapshots`.
2. **Vector Index**: Indexes posts into Chroma vector storage.
3. **Voice Learning**: Extracts stylistic nuances and tone into `VoiceProfile` records.
4. **Niche Inference & Competitor Discovery**: Infers the content niche, finds competitor handles on the network (excluding user's own handle), and generates winning frameworks.

### B. Volume Validation & Anchor Persona System
- **Volume Threshold (`MIN_POSTS = 5`)**: If a new connection has fewer than 5 posts (e.g. connecting a new LinkedIn account with 4 posts), Lumi will **not** attempt a noisy, low-confidence voice extraction.
- **Anchor Persona Inheritance**: The account with the highest volume of authentic content (e.g. an established X account) serves as the anchor persona. Thin connections automatically inherit the anchor persona's voice and active niche preferences without overwriting anything.
- **Cross-Network Framework Access**: If a network restricts third-party public scraping (e.g. LinkedIn), `latest_report` automatically falls back to your anchor profile's frameworks discovered on X.

---

## 4. Meta Reasoning Engine & Multimodal Capabilities

Lumi integrates Meta's Model API (`https://api.meta.ai/v1`) as its primary reasoning and intelligence provider:

### Model Allocation Matrix
| Capability | Model | Provider / Endpoint | Fallback |
| :--- | :--- | :--- | :--- |
| **Deep Reasoning & Frameworks** | `muse-wonder-1.0` | Meta (`POST /v1/chat/completions`) | `openai/gpt-oss-120b` (Groq) |
| **Fast Tool-Calling Agent Loop** | `muse-spark-1.3` | Meta (`POST /v1/chat/completions`) | `openai/gpt-oss-20b` (Groq) |
| **Voice / Audio Transcription** | `muse-voice-transcribe-1.0` | Meta (`POST /v1/asr/transcribe`) | `whisper-large-v3-turbo` (Groq) |
| **Visual Media Analysis (Planned)** | `sam-3.1` / `muse-image-1.0` | Meta Vision API | Gemini 3.5 Flash |

### Multi-Tier Architecture
- **Tier `reasoning` / `large`**: Dispatched to `muse-wonder-1.0` for competitor framework discovery, rubric evaluations, style extraction, and complex content generation.
- **Tier `small`**: Dispatched to `muse-spark-1.3` for sub-second agent tool iterations and RAG extraction.
- **Voice STT**: Native `Transcriber` uploads user voice audio directly to Meta's `/v1/asr/transcribe` with automatic fallback to Groq Whisper.
- **Fault-Tolerant Fallback Chain**: `Meta` $\rightarrow$ `Groq` $\rightarrow$ `Gemini` $\rightarrow$ `OpenRouter`.

---

## 5. Key API Endpoints

### Intelligence & Niche Radar
- `GET /api/v1/intelligence/niche-preferences/active`
  - Returns active niche title, keywords array, and tracked competitor handles.
  - Used by the n8n Niche Radar automation to drive dynamic searches.
- `POST /api/v1/intelligence/niche-reports/ingest`
  - Ingests multi-platform framework winners, outlier scores, and evidence references.

### Chat & Profiles
- `POST /api/v1/chat` & `POST /api/v1/chat/stream`: Chat with the AI agent.
- `GET /api/v1/profiles`: List user's connected social profiles.
- `POST /api/v1/profiles`: Create a new profile.
- `POST /api/v1/profiles/{id}/refresh`: Refresh posts and recompute metrics on demand.

---

## 5. Running Locally

```bash
# 1. Start local Postgres
uv run python scripts/dev_postgres.py --keep-alive

# 2. Start Django ASGI backend
$env:DJANGO_SETTINGS_MODULE="config.settings.dev"
uv run uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --reload

# 3. Start Frontend
cd frontend
npm install
npm run dev
```

---

## 6. Testing

```bash
# Run auto niche & competitor tests
uv run pytest apps/intelligence/tests/test_auto_niche_competitors.py

# Run all intelligence tests
uv run pytest apps/intelligence/tests/

# Run linting
uv run ruff check .
```
