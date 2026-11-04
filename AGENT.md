# AGENT.md - Agent Operating & Progress Log

## Mission
Autonomous AI Social Media Agent & Content Engine (Lumi).
This document logs progress, architecture, implemented capabilities, and what remains to be completed.

---

## 1. What Has Been Done

### Meta Model API Integration (`https://api.meta.ai/v1`)
- Configured Meta API key in `lumi/.env` (gitignored).
- Updated `AIConfig` with:
  - `meta_reasoning_model = "muse-wonder-1.0"` (1M context flagship reasoning model).
  - `meta_fast_model = "muse-spark-1.3"` (Sub-second agent loop and tool routing).
  - `meta_voice_model = "muse-voice-transcribe-1.0"` (`POST /v1/asr/transcribe` ASR audio transcription).
  - `meta_base_url = "https://api.meta.ai/v1"`.
- Provider Chain (`lumi_ai/providers/chain.py` and `factory.py`):
  - Updated with tier models (`reasoning`, `large`, `small`).
  - Added live fallback chain across Meta -> Groq -> Gemini -> OpenRouter.
- Speech-to-Text (`lumi_ai/providers/audio.py`):
  - Integrated Meta ASR endpoint (`POST /v1/asr/transcribe`).
  - Verified live endpoint with HTTP 200 on sample audio.

### Accurate Account Understanding & Demographic Grounding
- Overhauled `NICHE_PROMPT` in `apps/intelligence/tasks.py` to extract:
  - Demographics: Explicitly detect the creator's location (Nigeria, Lagos, West Africa), regional tech ecosystem markers (TechCabal, Moonshot conference, NITDA Nigeria, Raenest), and Nigerian Pidgin English context.
  - Creator Archetype: Founder, creative builder, motion/video designer, building in public.
  - Geo Scope: Formats `niche_key` with ISO country code (e.g. `nigerian-tech-founder-creative-builder:ng`).
- Full Corpus & Network Inspection:
  - Analyzed the creator's 123 posts in PostgreSQL.
  - Extracted network interaction graph (`@EditByAdonis`, `@Ifeanyi_Maulepe`, `@ahiakwo_john`, `@tsola_ps`, `@timmyisagod`, `@honour_can_code`, `@mishaelishola_`).
  - Sampled up to 35 rich posts to feed the reasoning model for accurate persona grounding.

### Strict Aggregator & Bot Exclusion
- Added `EXCLUDED_PEER_HANDLES` blacklist:
  - Banned community aggregators and bot hashtags: `buildinpublic`, `indiehackers`, `producthunt`, `techcrunch`, `ycombinator`, `startups`, etc.
  - Banned global billionaires/celebrities: `sama`, `karpathy`, `levelsio`, `elonmusk`, `paulg`.
- Enforced across `_rank_authors`, `_clean_handles`, and candidate peer extraction.
- Removed fake `@sama` / `@karpathy` hardcoded fallbacks from frontend `WinnersCard.tsx`.

### Automatic Retry Loop & Framework Synthesis
- Added retry loop (up to 3 attempts) in `_ensure_niche_and_competitors` to retry account understanding, niche research, and peer pipeline execution until complete.
- Implemented `_synthesize_niche_frameworks` using Meta reasoning model to extract battle-tested frameworks when third-party scraping has insufficient outliers.
- Successfully evaluated `@atehofficial` (Profiles 1, 3, 4):
  - Niche: `Nigerian Tech Founder & Creative Builder` (`geo_scope="ng"`).
  - Status: `ok`.
  - Extracted Frameworks:
    1. *The Pidgin Dev Pain Dump* (lift=2.6, conf=0.91)
    2. *The Public Shame Accountability Pact* (lift=2.4, conf=0.89)
    3. *The Clout-to-Results Breakup Debate* (lift=2.3, conf=0.84)
    4. *The Ecosystem Alignment Recap* (lift=2.1, conf=0.86)

### Schema & Vector Store Reliability
- Added field validators in `VoiceAnalysis` (`lumi_ai/competitors/schemas/peer.py`) to clamp `humor` (0-3) and `formality` (1-5), eliminating Pydantic validation drops.
- Reset and re-indexed Chroma vector collections (`voice_corpus`, `peer_posts`) with `onnx-minilm-l6-v2`.
- Safe error handling in `get_peer_advice` for vector retrieval.

### Email Transparency
- Confirmed that Lumi does NOT currently have active SMTP credentials configured.
- `notifications@lumiai.com` referenced in the n8n template was an unconfigured prototype placeholder.
- Notifications and updates currently operate in-app.

---

## 2. What Is Left to Do

1. **Transactional Email / SMTP Integration**:
   - If outbound email notifications are required, wire a real provider (e.g. Resend, SendGrid, Amazon SES) in `apps/core/` and configure valid credentials in `.env`.
2. **Audio Recorder Button in Chat UI**:
   - Wire a microphone recording button in the frontend chat to send recorded voice memos directly to `POST /api/v1/intelligence/profiles/{id}/transcribe/`.
3. **Continuous Peer Post Ingestion**:
   - Establish scheduled background polling for tracked Nigerian founder handles to keep the peer post corpus fresh on a daily basis.
4. **Multi-Account Profile Switcher Polish**:
   - Enhance the UI toggle between multiple connected accounts (e.g. switching between X and LinkedIn) so users can view platform-specific frameworks and voices side by side.
