# Codename Jo → Lumi integration plan

**Status:** phase 1 voice (§3.3) and the tool-argument fix (§4a item 2) are **built and landed** (2026-10). Phase 2 (§3.4) awaits the `OPENAI_API_KEY` decision; §4a items 1, 3–9 are unbuilt.
**Source:** full read of `github.com/kiloforgeai/codenamejo` (local clone `C:\Users\USER\Downloads\codenamejo`, 626 files, branch `master` @ `b9b1956`) by three analysis agents (architecture, voice pipeline, feature inventory).
**Priority from the brief:** voice chat first, then everything else that maps.

---

## 1. What Codename Jo is

A hands-free **voice assistant for Gmail/Calendar**, shipped as an iOS SwiftUI app (+ watchOS, Live Activity, CarPlay) that runs **entirely on-device on the user's own OpenAI key**. The only hosted piece is a stateless Google OAuth token shim that stores nothing.

| Piece | Where it runs |
|---|---|
| Voice session (`gpt-live-1`) + reasoning model (`gpt-5.6-luna`) | OpenAI, called from the phone (WebRTC + `/v1/responses`) |
| Mail ranking, summaries, per-category playbooks | the phone, on the user's key |
| Queue / profiles / history / settings | one local SQLite file (GRDB, 48 migrations) |
| Connector credentials (Google, Notion, Slack, GitHub, MCP) | the phone's Keychain |
| Google sign-in/refresh | thin stateless token shim, no DB, never logs tokens |

Two agentic loops share one toolset: the live voice call, and a **dispatch worker** for long jobs that keeps running after the user hangs up and reports back on the *next* call.

---

## 2. Does it map to Lumi? (concept by concept)

Lumi = chat-based AI creator agent for X: React web frontend, FastAPI backend, `run_agent_loop` with 19 registered tools, Groq→OpenRouter provider chain, Xpoz/PFM data sources.

| Codename Jo concept | Lumi equivalent | Verdict |
|---|---|---|
| Voice session (speaker) + brain (reasoning) split | PromptBar voice mode + existing `run_agent_loop` | **Take — this is the whole voice plan (§3)** |
| Turn detection (SmartTurn + Silero, 900 ms stall fallback) | browser silence endpointing | **Take the policy, not the model** |
| Barge-in (`response.cancel` + `output_audio_buffer.clear`) | realtime phase only | **Take** |
| Wait-beats ("mm, one sec") + `isTakingLong` at 3.5 s | tools can take 3–45 s (Xpoz, LLM, backfill) | **Take — highest UX value per line of code** |
| Dispatch worker (slow work off the turn, honest "unresolved" recovery) | backfill / voice-extract / niche scans currently block the turn | **Take** |
| Durable write outbox (≤12 tries/24 h, exp backoff, honors Retry-After) | PFM/Xpoz writes are fire-once, no retry | **Take** |
| Turn history with FTS search + 30-day retention | `chat_messages` has no search, no retention | **Take** |
| 4-tier context retrieval (exact → FTS → vector → recency, floor 0.55) | Chroma-only retrieval (`recall_memory`, `get_peer_advice`) | **Take as hardening** |
| Local/offline voice fallback | browser `speechSynthesis` fallback | **Take (the honest-degradation pattern)** |
| `SessionState` + level metering (level, not transcription, drives the UI) | no voice UI at all today | **Take** |
| Per-install identity, every row user-scoped | single-user hardwired (`AtehOfficial`, no auth) | **Take as the prerequisite for multi-user** |
| Latency instrumentation (`DialTiming`, `TurnLatency`, medians) | `turn timing:` log line only | **Take** |
| Onboarding flow (sign-in → connect → mic → say-it → speech) | connect-account only | **Take, abridged** |
| Importance ranking of mail | ranking of trending posts / audience signals | **Maybe** — see §4 |
| MCP connectors (Notion/Slack/GitHub…) | no MCP at all | **Take in one direction only** — expose Lumi's tools as an MCP server (§4) |
| Google token shim | N/A — no secret to hide, no OAuth we own | **Skip** |
| Live Activity / CarPlay / watchOS / App Intents | web app | **Skip the Apple surfaces, take the idea → Web Push spike alerts (§4)** |
| On-device LLMs, LoRA fine-tune, Paradee TTS | browser, no local models | **Skip** |

---

## 3. Voice chat (the priority)

### 3.1 The hard constraint: which provider can serve audio?

Lumi today has **no `OPENAI_API_KEY`** — providers are Groq / OpenRouter / OpenLux via the OpenAI-compatible chat SDK, and neither Groq nor OpenRouter offers a realtime audio channel. Three honest options:

| Option | Stack | New keys | Cost | Duplex | Latency (first audio) | Verdict |
|---|---|---|---|---|---|---|
| **A. Groq STT + agent + Groq TTS, round-trip** | MediaRecorder → `POST /voice/transcribe` (Whisper-class STT) → existing `run_agent_loop` → `POST /voice/speak` (TTS) → audio chunks to browser | none (reuse `GROQ_API_KEY`) | ~free tier | half-duplex | ~3–6 s | **Build this first** |
| **B. OpenAI Realtime WebRTC** (what Jo does) | backend mints an ephemeral client secret; browser speaks WebRTC straight to OpenAI; tools still execute on FastAPI | `OPENAI_API_KEY` (new) | ~$0.05–0.15/min voice + reasoning tokens | full-duplex, server VAD, native barge-in | ~0.5–1.5 s | **Phase 2 upgrade** |
| **C. Browser Web Speech API** | `SpeechRecognition` + `speechSynthesis`, no server audio | none | free | half-duplex | ~1–2 s | **Degraded fallback only** (Chromium-tied, robotic voices) |

Jo's own architecture is the argument for A→B: its "local voice" path (option C analog) exists purely so the call *always answers*, and its live path is WebRTC. We follow the same shape: **A works today on keys we already hold; B is the fidelity upgrade once an OpenAI key is approved.**

*Model availability and file-format support on Groq must be verified with one `curl` at build time before any code is written (Jo's `PRINCIPLES.md:21-23`: "a belief that stood for a week in three files was undone by one curl").*

### 3.2 What we port from Jo's voice pipeline

| Jo piece | Files | How Lumi uses it |
|---|---|---|
| **Speaker/brain split** — voice front-end never reasons; a client brain does | `LivePrompt.swift:106-113` (`delegation: client`), `LiveClientBrain.swift` | Lumi's brain stays `run_agent_loop` + the 19 tools. Phase 1: STT/TTS are the speaker. Phase 2: OpenAI Realtime is the speaker, FastAPI runs tools. |
| **Turn-end policy** — first judgement at 0.25 s, then every 0.2 s, threshold decays 0.85→0.5, 1.5 s of silence ends it; "sound without words is not a turn" | `SmartTurnPolicy.swift:3-38`, `LocalTurnPolicy.swift:6`, `LocalVoiceCall.swift:248-252` | Port the *policy numbers* as a browser-side endpointer (RMS silence + transcript-stall 900 ms). We do not ship a turn model in v1. |
| **Phrase-buffered streaming TTS** — split the streamed reply on sentence boundaries, synthesise chunk-by-chunk, first-audio logged | `SpokenPhraseBuffer` via `LocalVoiceCall.swift:354-385` | Speak the SSE reply as it streams instead of waiting for `done` — the single biggest latency win in phase 1. |
| **Wait-beats + `isTakingLong`** | `LiveSessionAdapter.swift:1045-1054`, `RealtimeService.swift:334-403` | While a tool runs >3.5 s, show/say "one sec — checking Xpoz". Lumi's tools genuinely take that long. |
| **Barge-in semantics** — cancel speech, never cancel in-flight tool work | `FullDuplexVoiceClient.swift:1051-1094` | Phase 2: `response.cancel` + `output_audio_buffer.clear`. Phase 1: tap interrupts TTS only. |
| **Echo discipline** — half-duplex locally (mic off while speaking), full-duplex with AEC on the live path | `LocalVoiceCall.swift:4-5`, `FullDuplexAudioSession.swift:10-12` | Phase 1 is half-duplex by construction (Web Audio `AnalyserNode` level gate); phase 2 relies on WebRTC APM. |
| **State machine + level-driven UI** — `disconnected/connecting/ready/listening/processing/responding/error`; metering never renders user words | `RealtimeService.swift:40-67`, `SpeechIndicator.swift:4-5` | New voice dock in `PromptBar` with the same states + a level meter. Lumi *does* show the partial transcript (it's a chat), unlike Jo — deliberate divergence. |
| **Honest failure copy** | `VoiceFailureText.swift:8-31` | Mic denied / STT failed / TTS failed each get a plain sentence, never a silent failure (matches Lumi's no-fabricated-data rule). |

### 3.3 Phase 1 — push-to-talk voice in the existing chat ✅ *(built 2026-10)*

No new keys, reuses the agent loop, tools, SSE stream and history exactly as they are.

**What landed (differs from the original plan in three ways):**
- **STT format:** PCM capture via `ScriptProcessorNode` → WAV (not MediaRecorder webm/opus) — no codec guessing between browsers, Whisper accepts WAV everywhere.
- **TTS:** browser `speechSynthesis` only — the Groq account exposes no TTS model (verified via `GET /openai/v1/models`). A server-side `/voice/speak` route was deliberately not built; it can be added when a TTS-capable key exists.
- **State machine:** `idle → listening → transcribing → idle` (speak happens in App, not PromptBar; no separate `thinking`/`speaking` PromptBar states).

**Backend (FastAPI)** — `app/routers/voice.py`, registered in `main.py`:
1. `POST /voice/transcribe` — multipart WAV → Groq `whisper-large-v3-turbo` → `{text, duration_ms}`. Audio discarded; nothing persists. 422 empty, 413 >25 MB, 502 provider failure (honest error, never fabricated text). Audio client: `providers.py:get_audio_provider()` (plain `AsyncOpenAI`, lazy, separate from neatlogs-wrapped chat providers).

**Frontend (`C:\Users\USER\Downloads\lumi\frontend\src`)**:
2. `voice/recorder.ts` — `MicRecorder`: PCM capture → WAV blob; silence endpointer (120 ms poll, 1.5 s quiet after ≥0.5 s speech, 30 s hard cap).
3. `voice/speak.ts` — `speak(text)` sentence-splits → queues `SpeechSynthesisUtterance`s; `stopSpeaking()` generation counter prevents cancelled phrases from chaining.
4. `api/voice.ts` — `transcribeWav(blob)` → `POST /voice/transcribe`.
5. `PromptBar.tsx` — mic button toggles `voiceState`; silence endpointer auto-stops and auto-sends; manual tap stops and sends; errors shown inline; `onSend(text, { voice: true })`.
6. `App.tsx` — `send(raw, opts?)` sets `voiceReplyRef`; on completion, `speak(replyText)` if voice was used; new send calls `stopSpeaking()` first (barge-in).

**Verification:** `uv run ruff check .`, `uv run pytest` (200 passed, incl. 4 voice-route tests + 6 tool-error tests), live smoke test (tone WAV → Groq → `{"text":".","duration_ms":2514}`).

### 3.4 Phase 2 — full-duplex realtime *(needs `OPENAI_API_KEY` decision)*

1. `POST /voice/session` → OpenAI ephemeral client secret with our `build_system_prompt()` instructions + the **existing** tool schemas attached.
2. Browser opens WebRTC directly to OpenAI (no audio through our server — same privacy shape as Jo).
3. Tool calls arrive on the data channel and execute on FastAPI through `tool_registry.call_tool` — *this depends on the tool-argument hygiene fix already proposed for `loop.py`/`registry.py`: a hallucinated kwarg must never kill a voice turn*.
4. Server VAD gives native barge-in; port `LiveSessionAdapter`'s settle-timers (500 ms fast-action / 1 s normal) for transcript finalization.
5. Keep phase 1 as the fallback when the key is missing or the session fails — exactly Jo's "the phone's voice steps in on its own whenever the live call can't connect".

### 3.5 Phase 3 — polish

Voice picker + preview, dial/turn latency surfaced in a debug panel (Jo's `DialTiming` medians), "still working on it…" presence line, spoken confirmation of dispatched/background jobs, saved-voice-command shortcuts (Jo's custom commands).

### 3.6 Decisions needed before phase 1 code

1. Approve phase 1 (no new keys) — **yes/no**.
2. `OPENAI_API_KEY` for phase 2 at ~$0.05–0.15/min — **get it / defer**.
3. Mic UX: hold-to-talk vs click-to-toggle vs always-listening — Jo chose always-listening hands-free; on a shared desktop, **click-to-toggle** is my recommendation.

---

## 4. Other features worth integrating (ranked)

### 4a. Build list — ranked by value-per-effort for Lumi

1. **Dispatch/background job handoff** — off-turn long jobs (backfill, voice extraction, niche scans, weekly recon) with a durable job table, honest `unresolved` recovery at the next turn, results surfaced on the following message. Jo: `DispatchWorker.swift:5-8` (16 rounds / 270 s budget), `DispatchJob.swift:48-62`. *Directly fixes Lumi's "one slow tool blocks the answer" UX.*
2. **Tool-failure feedback + argument hygiene** ✅ *(built 2026-10)* — a tool that raises returns `{"error": ...}` to the model instead of killing the turn; unknown kwargs filtered in `call_tool`. Jo's rule 18 ("surface failures, never swallow") + its broker's speakable refusals (`FullDuplexBroker.swift:409-452`). Landed in `app/agent/loop.py` + `app/tools/registry.py` + `tests/test_agent_tool_errors.py`.
3. **Wait-beats / presence lines** — "one sec…" during slow tools; `isTakingLong` at 3.5 s. Jo: `RealtimeService.swift:334-403`, `LiveSessionAdapter.swift:1045-1054`.
4. **Confirm-first guardrails for irreversible actions** — Jo refuses a never-before-mailed recipient without `recipient_confirmed: true` and reads the target back (`LiveToolSchemas.swift:201`, `prompts/base/confirm-first.md`). Lumi publishes to X: verify the target handle and confirm before any post/send verb.
5. **Durable write outbox with backoff** — retries for PFM/Xpoz writes: ≤12 attempts/24 h, exponential cap 15 min, honor `Retry-After`, only throttling/5xx retryable, failures reported in the originating conversation. Jo: `PendingMailWrites.swift:7-28`.
6. **Fast actions (side-channel keyword commands)** — Jo's `LiveFastAction` fires an action straight from a deterministic transcript parser *while the model is still talking*. Lumi analogue: "post it" / "skip" / "use that" executes `submit_action` without a model round-trip.
7. **Voice memo → post draft** — record an idea, transcribe, queue, then hand it to `repurpose_caption` as `source_text`. Jo's memo queue (`QueuedMemo.swift:7-21`, `MemoWidget`). *The creator-agent version of Jo's offline memos; pairs with §3 phase 1.*
8. **Web Push spike alerts** — Jo's Live Activity concept, web-native: `check_trending` fires a notification with the post + velocity. (Needs VAPID + a push route; also fixes the fact that the frontend never polls `/alerts/unread`.)
9. **Message search** — FTS over `chat_messages` with scope filters (Jo's `TurnStore.swift:216-307`, 30-day retention), surfaced as a search box in the sidebar. Lumi's sidebar already has a *local* search over localStorage only.
10. **Saved commands / recipes** — pinned multi-step prompts (Jo's `CustomCommandStore`, dispatch `worker.md` pinned steps). Lumi analogue: "weekly recon" = one saved prompt that runs `check_niche_trends` + `discover_and_extract_niche_frameworks` + `get_peer_advice` in sequence.
11. **Per-account publish mode (draft vs auto-post)** — Jo's mail-mode handoff: an execution-time preference read by the send tools, changeable later, re-asked on sign-out (`EmailOnboarding.swift:5-11`, PR #10). Lumi's exact analogue for connected X accounts.
12. **Standing rules + creator memory** — Jo's `set_rule` / `search_context` / `save_context`. Lumi already has `remember`/`recall_memory`; add explicit standing rules the agent must honor every turn.
13. **Signal importance ranking** — Jo's hybrid scorer: deterministic signals → batched LLM bands (`high|normal|low`, 1–10, an 8-word `why`, never throws — a failed batch stays middle-band) → hard clamps (`MailImportance.swift:142-316`). Apply to trending/niche matches instead of `min_likes` alone; feeds `listening_matches`.
14. **Custom-MCP surfacing layer** — `mcp_<server>_<tool>` naming, a never-throw runner turning every 401/429/5xx into plain text, 24 KB result clipping (`CustomMCPTools.swift:19-159`). Pair with the reverse direction: expose Lumi's 19 tools *as* an MCP server.
15. **Context retrieval hardening** — 4-tier (exact key → FTS → vector → recency, floor 0.55) around Chroma, so an outage degrades instead of failing. Jo: `LocalContextStore.swift:298-358`.
16. **Onboarding arc with real side effects + resume** — scripted first run whose tutorial performs a genuine action, fully resumable after a hang-up (`prompts/onboarding/five-step*.md`, `OnboardingResume`). Lumi's: connect → voice → first recon.
17. **Coaching lesson rotation** — `coaching.json` keyed by capability id, one tip at a time in-band (`coach_capability`).
18. **Contract/parity tests** — Jo pins session tool+prompt lists against a fixture (`Fixtures/live-session-parity.json`) and swaps tool transports via typealiases for canned answers. Lumi analogue: a test pinning `list_tool_specs()` (names + required params) so schema drift fails CI, plus systematic swappable transports for Xpoz/PFM.
19. **Quota/credit guards** — Jo's `GmailQuota`/`CalendarQuota`/Slack-50-sweep/dispatch-budget pattern → an `XPOZ_RUN_CREDIT_BUDGET` enforced per tool call (already an open item in the niche/peer pipeline plans).
20. **Latency instrumentation** — first-audio and per-tool timing surfaced in a debug panel, not just the log line (Jo: 20-dial medians, `DialTiming`).
21. **Honest degradation copy** — per-failure plain-language messages (`VoiceFailureText` pattern) across Xpoz/PFM/Chroma failures, so the `⚠️` surface always says what to do next.

### 4b. Mapped but "needs rework" (queued, not planned)

Queue walk / next-item-in-advance turns (a content-walk UI, not a chat concept) · crossing & other-mailbox prefetch (a latency-hiding idea, portable to streaming feeds) · profile handoff between workspaces (Lumi is single-user today) · bulk cleanup verbs (`modify_matching` / unsubscribe → bulk dismiss of trends) · hosted-MCP OAuth client (DCR+PKCE — belongs server-side in FastAPI if we ever consume connectors).

### 4c. Not applicable (see §5)

Live Activity / Dynamic Island · watchOS audio companion · CarPlay · Shortcuts/iMessage bridge · on-device Gemma+LoRA fallback · BYO-key client-execution (Lumi is server-keyed — though the privacy stance "nothing leaves except the API calls" is worth quoting in our own docs).

---

## 5. Deliberately NOT taking

- **Google token shim** — we hide no OAuth client secret and store no third-party grants.
- **On-device LLMs / LoRA / Paradee TTS / SmartTurn model weights** — browser target, no local inference; our turn policy comes from numbers, not a model.
- **Apple surfaces** — Live Activity, CarPlay, watchOS, App Intents (their web analogues are Push/notifications/PWA).
- **Keychain/GRDB-style local store** — Lumi's DB is the server's; per-install identity is the piece worth taking (§2), not the storage layer.

---

## 6. Constraints this plan must respect

- **Plan-first:** each phase above needs explicit go before code (repo `AGENTS.md` working process).
- **Doc sync in the same change:** any tool/data-flow change updates `AGENTS.md`, `docs/flow-map.md`, `docs/flow-map.html`.
- **Secrets rule:** env var *names* only (`GROQ_API_KEY`, `OPENAI_API_KEY`…); values live in `.env` / Railway only.
- **Credit reality:** Xpoz free plan is 500 one-time credits (search = 2/query) and PFM's key is dead — voice work must not add credit-burning steps to a turn.
- **No auth yet:** every route trusts a client-supplied `profile_id`; voice routes inherit that exposure and must not make it worse (no audio persistence).

---

## 7. Immediate next actions (pending approval)

1. Phase 1 voice build (§3.3) — backend routes, PromptBar voice dock, phrase-buffered speech, tests, doc sync.
2. The separately proposed tool-argument hygiene fix (`registry.call_tool` filters unknown kwargs; `loop.py` feeds tool failures back to the model instead of aborting the turn) — **a prerequisite for phase 2 and a live bug today** (`get_peer_advice() got an unexpected keyword argument 'url'`).
3. ~~Amend §4 with the feature-inventory agent's full sweep~~ — **done**: §4a is the ranked build list (21 items), §4b/§4c record what is queued and what we refuse.

**Awaiting your go:** (a) phase 1 voice build §3.3 · (b) the tool-argument fix item 2 · (c) `OPENAI_API_KEY` for phase 2 · (d) mic UX (my pick: click-to-toggle). Plus one spelling call — the tagline you gave keeps **"loosing"**; say the word and I'll make it "losing".
