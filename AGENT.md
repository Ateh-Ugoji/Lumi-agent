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

### 7. Continuous Peer Post Ingestion
- Registered `PEER_SYNC_KIND = "peer.sync"` on `apps.core.jobs`.
- Implemented `sync_peer_posts(ctx: JobContext)`:
  - Iterates active `NichePreference`s and tracked peer founder handles.
  - Fetches fresh public posts via `social.fetch_user_posts(platform, handle, since, limit)`.
  - Persists new posts into PostgreSQL through `PeerPostRepo().save_peer_posts()`.
  - Embeds and indexes fresh posts into Chroma `peer_posts` collection via `indexer.index_peer_posts()`.
- Registered Celery `@shared_task(name="intelligence.sync_peer_posts")` for periodic Celery Beat / daemon execution.
- Verified with targeted test suite `apps/intelligence/tests/test_peer_sync_task.py` (2 passed).

### 8. Phase 4: Soft-Tiering Winner Selection
- Replaced brittle hard floor (`< 8` winners causing immediate `insufficient_data` collapse) with graceful tri-tier degradation in `lumi_ai/competitors/winners.py`:
  - **Tier A ($\ge 8$ Winners)**: `status="ok"`, `data_tier="high"`, `confidence_tier="high"`.
  - **Tier B (3–7 Winners)**: `status="ok"`, `data_tier="moderate"`, `confidence_tier="moderate"`, records warning `"Report based on moderate sample of N winners (data_tier=moderate)"` without discarding valid winners.
  - **Tier C ($< 3$ Winners)**: `status="insufficient_data"`, `data_tier="sparse"`, `confidence_tier="provisional"`, activates reasoning LLM synthesis fallback (`_synthesize_niche_frameworks`) so the user is never left without frameworks.
- Extended schemas in `schemas/peer.py`: `confidence_tier` in `NicheFrameworkReport`, `data_tier` in `WinnerSelection`.
- Verified with 14 unit tests in `lumi_ai/tests/competitors/test_winners.py` (all passed).

### 9. Phase 5: Synthesis Enhancements & Frontend WinnersCard Badges
- Enhanced `WinnerPeer` in `lumi/frontend/src/components/WinnersCard/WinnersCard.tsx`:
  - Added `peerRole`, `gradingScore`, `relevance` fields.
  - Implemented visual role pills with distinct semantic badge tokens:
    - `direct_competitor` -> "Direct Competitor" (blue pill).
    - `parallel_founder` -> "Parallel Founder" (emerald/green pill).
    - `aspirational_leader` -> "Aspirational Leader" (purple pill).
    - `co_builder` -> "Co-Builder" (amber pill).
  - Implemented match percentage score badge (`92% Match`).
  - Added ecosystem geo alignment tag (`🇳🇬 NG`).
  - Added avatar image with initials fallback.
- Added comprehensive responsive styles in `WinnersCard.module.css`.

### 10. Multi-Account Profile Switcher
- Added instant 1-click account switching in `lumi/frontend/src/components/Sidebar/Sidebar.tsx`:
  - `profileSwitcherBar`: Horizontal rail pill buttons (e.g. `[ 𝕏 @atehofficial ] [ in @ateh ]`) displaying side-by-side connected platforms with active highlight.
  - `WorkspaceMenu`: Dedicated "Connected Accounts" section displaying each connected profile with platform badges (`𝕏`, `in`) and active checkmarks.
  - Connected `profiles`, `activeProfileId`, and `onSelectProfile={selectProfile}` in `App.tsx`.
- Typechecked and built cleanly with Vite in 134ms.

### 11. Audio Recorder Button in Chat Composer
- Enhanced microphone recorder in `lumi/frontend/src/components/PromptBar/PromptBar.tsx`:
  - Real-time animated equalizer bars (`eqBars`) during active audio capture.
  - Bouncing spinner during transcribing state (`micSpinner`).
  - Integrated with Meta ASR / Groq endpoint `POST /api/v1/voice/transcribe`.
  - Clean stop-and-send or draft auto-population.
  - Verified with 23 backend transcription tests and 79 frontend unit tests passing.

### 12. LinkedIn Competitor Scraping & Social Data Ingestion (Initial Build)
- Implemented `LinkedInSocialData` adapter in `apps/connections/linkedin_social.py` conforming to `ports.SocialData`:
  - `fetch_user_posts(handle, since, limit)`: Reads LinkedIn member and creator posts via connected LinkedIn OAuth provider (`r_member_social`) or cached repository posts with metric normalization.
  - `search_posts(query, limit)` & `get_user(handle)`: Resolves LinkedIn creator handles and post queries into typed `PostIn` / `UserInfo`.
  - Wired via `RunSocialData` in `apps/intelligence/wiring.py` to automatically route `platform="linkedin"` requests.
  - Enabled LinkedIn peer pipeline execution in `apps/intelligence/tasks.py` for profiles with sufficient volume, while preserving anchor persona framework inheritance for sparse profiles.
  - Verified with 2/2 tests in `apps/connections/tests/test_linkedin_social.py` passing.

---

## 2. What Is Left to Do

### Open Action (Immediately Actionable Next Tasks)
1. **Multi-Platform Competitor Scraping Expansion (Open/In Progress)**:
   - Initial LinkedIn adapter built (`apps/connections/linkedin_social.py`). Next action: expand proxy and headless scraping fallbacks for unauthenticated third-party competitor LinkedIn profiles (e.g., via RapidAPI or session proxies).
2. **Celery Beat Recurring Schedule**: Add periodic crontab schedule entry (e.g. every 12 or 24 hours) in celery config to invoke `intelligence.sync_peer_posts` automatically in production.
3. **Transactional Outbound Email Provider**: Connect real SMTP or transactional API provider (Resend, SendGrid, Amazon SES) in `apps/core/` for the n8n Niche Radar notification alerts.

### Planned (Architectural Roadmap & Future Enhancements)
1. **Multi-Platform Scrape Adapter Expansion (Planned)**:
   - Expand `ports.SocialData` to support automated public competitor feeds on Instagram and Facebook as official Graph API permissions or proxy endpoints become available.
2. **Extended Video Audio OCR & Visual Framing**: Add deeper frame-by-frame visual analysis for TikTok / Reels competitor winning posts.

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

