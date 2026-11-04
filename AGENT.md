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

---

## 3. Next-Gen Peer Schema & Competitor Grading Architecture (Architectural Plan)

> **CRITICAL DIRECTIVE: DO NOT ACT YET.**
> This section logs the architectural plan for grading competitors across a spectrum, removing brittle winner gates, and adding multi-dimensional lift. Do not make code changes until explicit user authorization.

### Key Architectural Pillars Planned

#### 1. Competitor Grading Spectrum & Entity Model (`NichePreferenceHandle` & `PeerProfile`)
- **Direct Competitor Scarcity Problem**: Exact 1:1 direct SaaS competitors are scarce in early-stage niche founder communities (e.g. Nigerian tech founders / creative builders). Treating peers as a binary "is direct competitor" or "not" causes candidate starvation or falls back to irrelevant global celebrity accounts.
- **The 4-Tier Grading Spectrum**:
  - `direct_competitor` (Tier 1, Weight 1.0): Direct SaaS/tool alternatives.
  - `parallel_founder` (Tier 2, Weight 0.85): Builders at similar stage in the same geographic/demographic ecosystem facing identical infrastructure, currency, and market realities.
  - `aspirational_leader` (Tier 3, Weight 0.70): Founders 1-2 stages ahead who set content cadence and high-engagement benchmarks.
  - `co_builder` (Tier 4, Weight 0.60): Network graph collaborators with joint accountability pacts.
- **Fields to Add**:
  - Pydantic: `PeerRole`, `RelevanceBreakdown` (`geo_alignment`, `icp_overlap`, `content_resonance`, `stage_comparability`), `PeerGrading`.
  - Django Model: `NichePreferenceHandle` receives `peer_role`, `grading_score`, `relevance_breakdown`, `ecosystem_tags`, and `rationale`.

#### 2. Soft Tiering & Resilience Engine for Winner Selection (`MIN_WINNERS_FOR_REPORT`)
- **Problem**: The hard floor `MIN_WINNERS_FOR_REPORT = 8` collapses the entire report into `insufficient_data` if an account has 3–7 viral winner posts.
- **Tri-Tier Volumetric Degradation**:
  - **Tier A ($\ge 8$ Winners)**: Pure statistical outlier engine (z-score > 1.5 against 4-week median), strict IQR percentile math, full lift table.
  - **Tier B (3–7 Winners)**: Hybrid statistical baseline + LLM synthesis. Computes lift on available winners, tags cognitive frameworks, produces actionable report with moderate confidence flag.
  - **Tier C ($< 3$ Winners)**: Synthesis engine derived from available peer posts + user interaction graph + founder niche anchor. Status remains `ok` (provisional), never empty.

#### 3. Multidimensional Lift Table Schema (`LiftRow`)
- **Problem**: Format and topic alone do not capture what causes posts to blow up in founder ecosystems.
- **Dimensions to Add to `LiftRow.dimension`**:
  - `language_register`: `nigerian_pidgin`, `nigerian_colloquial`, `formal_business`, `technical_deep_dive`, `blended_casual`.
  - `media_style`: `motion_design_video`, `screen_recording_demo`, `talking_head_video`, `screenshot_metric`, `screenshot_code`, `text_only_punchy`, `text_only_thread`.
  - `ecosystem_context`: `local_summit_conference`, `builder_infrastructure`, `client_to_saas_pivot`, `public_accountability`, `founder_debate_rant`, `general_educational`.
- **Pipeline Integration**:
  - `TAGGING_PROMPT` in `extract.py` extracts these 3 dimensions per post.
  - `PostAnalysis` in `peer.py` holds typed fields.
  - `lift_attributes()` and `build_lift_table()` compute lift ratios for each dimension.
  - Synthesizer surfaces key insights (e.g. *"Nigerian Pidgin + Motion Design Video demonstrates 2.6x lift over formal English text"*).

