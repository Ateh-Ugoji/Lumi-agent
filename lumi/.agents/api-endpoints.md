# API Endpoints

## Scope

MVP targets **X (Twitter) only**. All demo profiles are X accounts. Repurposing generates X-formatted output (280 char limit, thread support). Multi-platform repurposing is out of scope.

## Overview

The interface is chat-based. Most functionality is exposed as tools the agent calls, not as REST endpoints. The endpoints below are the minimal surface the frontend needs.

## Endpoints

### Chat

#### `POST /chat`

Agent loop entry point. Accepts a user message, runs the agent loop (LLM + tool calls), returns the response.

**Request body:**

```json
{
  "profile_id": 1,
  "message": "Repurpose this caption for Twitter and LinkedIn"
}
```

**Response:**

```json
{
  "role": "assistant",
  "content": "Here are two versions: ...",
  "tool_calls_made": ["classify_difficulty", "generate_caption", "check_must_keep", "judge_intact"]
}
```

**Notes:**
- The agent loop runs synchronously within this request. Each tool call executes inline.
- All messages (user, assistant, tool) are persisted to `chat_messages`.
- `profile_id` identifies the active profile. No auth token.
- If the agent triggers multiple tool calls (e.g. repurpose across platforms), they run sequentially within one request.
- Latency will be high (3–10s) due to chained LLM calls. The frontend should show a loading state.

---

#### `GET /chat/history`

Returns conversation history for rendering previous messages.

**Query params:**
- `profile_id` (required): which profile's chat to load
- `limit` (optional, default 50): number of messages
- `before` (optional): message ID for cursor pagination

**Response:**

```json
{
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "Connect my account",
      "created_at": "2026-10-10T12:00:00Z"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "Done. I pulled 42 posts and built your voice profile.",
      "created_at": "2026-10-10T12:00:03Z"
    }
  ]
}
```

**Notes:**
- Tool-role messages are internal to the agent loop. Filter them out or include them based on whether the frontend shows tool call details.
- Each profile has its own conversation history.

---

### Profiles

#### `GET /profiles`

List all seeded demo profiles for the profile switcher.

**Response:**

```json
{
  "profiles": [
    {
      "id": 1,
      "name": "Demo User 1",
      "platform": "instagram",
      "handle": "@demo1",
      "has_voice_profile": true,
      "listening_active": false
    }
  ]
}
```

---

#### `POST /profiles/{id}/select`

Set the active profile for the session. Clears or switches the chat context.

**Response:**

```json
{
  "profile_id": 1,
  "name": "Demo User 1",
  "voice_profile_exists": true,
  "post_count": 42,
  "listening_active": false
}
```

**Notes:**
- This is a UI-level action, not an agent tool. The frontend calls it when the user switches profiles.
- Returns enough context for the frontend to show the profile state without extra calls.

---

### Alerts

#### `GET /profiles/{id}/alerts/unread`

Returns posts with detected spikes that haven't been dismissed. The frontend polls this every few seconds to show toast notifications.

**Response:**

```json
{
  "alerts": [
    {
      "post_id": 17,
      "caption": "Why every API should...",
      "platform_post_id": "abc123",
      "alerted_at": "2026-10-10T14:30:00Z",
      "velocity": {
        "likes_per_hour": 45,
        "baseline_likes_per_hour": 12
      }
    }
  ]
}
```

**Notes:**
- Filtered by `alerted_at IS NOT NULL AND alert_dismissed = false`.
- The velocity data comes from the two most recent metric snapshots for that post.
- When the user acts on an alert (via chat), the agent calls `dismiss_alert` to set `alert_dismissed = true`.
- Poll interval: 5–10 seconds. The background poller writes alerts; this endpoint reads them.

#### `POST /voice/transcribe`

Uploads a short WAV clip (mono 16-bit PCM, produced by the browser's `MicRecorder`) and returns the transcribed text via Groq's `whisper-large-v3-turbo`. This is the STT half of the voice-chat integration (see `docs/codenamejo-integration.md` §3.1); TTS is browser-local (`speechSynthesis`) because the Groq account exposes no TTS model.

**Request:** `multipart/form-data` with a single `file` field (WAV blob, max 25 MB).

**Response:**

```json
{
  "text": "Do a fresh recon on the indie hacker niche",
  "duration_ms": 840
}
```

**Error codes:**
- `422` — empty upload or missing `file` field.
- `413` — upload exceeds 25 MB.
- `502` — Groq rejected the request or was unreachable; `detail` carries the exception type.

**Notes:**
- The uploaded audio is transcribed and discarded; nothing is written to the database.
- The frontend calls this after the silence endpointer (or a manual tap) stops the recorder, then auto-sends the transcript as the user's chat message.

### Handle search (added 2026-10-21)

The chat composer's `@`-menu. Thin delegation to the handle-search MVP core (`mvp/handle_search/server.py`) — the same handler functions the standalone :8010 bar uses, so there is exactly one code path. Only `GET /handles/search` can burn Xpoz credits (2/query, server-side cache-first with prefix-chain reuse, `MVP_XPOZ_LIVE` kill-switch, per-session budget); the other three are free.

#### `GET /handles/search`

**Query params:**
- `q` (required): the handle prefix typed after `@`. Under 2 chars returns `reason: "min_length"` with empty results (no external call).
- `context` (optional): up to the 3 words typed before the `@` — re-ranks results (never sent to Xpoz).

**Response:**

```json
{
  "query": "ateh",
  "context": "recon on the",
  "results": [
    {
      "handle": "AtehOfficial",
      "display_name": "Ateh Ugoji",
      "avatar_url": "https://...",
      "followers": 1234,
      "source": "db"
    }
  ],
  "live": false,
  "refreshed": false,
  "reason": "cache_exact",
  "live_queries_this_session": 0
}
```

**Notes:**
- `source` is `db` | `cache` | `live` — where this row came from on *this* search. `reason` is `null` when live ran clean; `cache_exact` (fresh negative cache), `live_disabled`, `budget_exhausted`, `min_length` otherwise.
- Results are a half-and-half mix: saved (memory-served) vs live (fresh-pull), exact typed handle first, filled to 10.

#### `GET /handles/saved`

Instant-suggest snapshot: local db ∪ remembered handles (`handle_mappings`), followers first. The composer loads it once and prefix-filters client-side per keystroke (0 ms, 0 credits), refreshing after each search/selection.

**Response:** `{ "results": [ ...same shape as search results... ], "count": 309 }` (≤ 500 rows).

#### `POST /handles/select`

Remembers a picked handle (`origin: selected` in `handle_mappings`). The composer fires and forgets — a failure never blocks tagging.

**Request body:**

```json
{
  "handle": "AtehOfficial",
  "platform": "x",
  "display_name": "Ateh Ugoji",
  "avatar_url": "",
  "followers": 1234,
  "selected_query": "ateh"
}
```

**Response:** `{ "remembered": true, "handle": "atehofficial" }`

#### `GET /handles/stats`

Credit meter + store counts. Free.

**Response:**

```json
{
  "live_queries_this_session": 0,
  "live_budget": 10,
  "live_enabled": true,
  "cache_ttl_minutes": 60,
  "saved_handles": 309,
  "known_db_handles": 11,
  "remembered_handles": 300,
  "remembered_by_origin": { "live": 265, "cache": 4, "niche": 30, "unknown": 1 },
  "cached_searches": 31
}
```

### MCP connectors — Google (added 2026-10-21)

In-backend MCP client (Streamable HTTP) exposing Google Drive/Docs tools to the agent as `mcp__<connector>__<tool>` functions. Full architecture, connector-config recipe, and the manual Google Cloud setup checklist live in `docs/mcp-connectors.md`. The three routes below exist only to run Google OAuth and report status — the connector tools themselves are **not REST endpoints**; they run inside the agent loop like every other tool.

#### `GET /mcp/google/connect`

Redirects the browser to Google's consent screen (scopes = union of `drive.readonly` + `drive.file` + `documents`, `access_type=offline`, forced consent so a refresh token exists). The `state` is an in-memory single-use random (CSRF guard for the callback).

**Response:** `302` to `https://accounts.google.com/o/oauth2/v2/auth?...` — or an honest **503** `{"error": "google_oauth_not_configured", "detail": "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET ..."}` when the OAuth client env vars are unset (never a fabricated consent URL).

#### `GET /mcp/google/callback`

Where Google redirects after consent. Query params: `code` (auth code), `state`, `error`. Exchanges the code for access + refresh tokens (server-to-server POST to `https://oauth2.googleapis.com/token`, never logged), upserts the `google` row in `mcp_auth_accounts`, and returns JSON.

**Response:** `{"connected": true, "scopes": ["..."]}` — or `{"connected": false, "error": "..."}` for a denied/unknown flow. (Like `GET /pfm/callback`, it returns JSON to the browser rather than redirecting into the SPA — known UX gap, same as PFM.)

#### `GET /mcp/google/status`

**Response:** `{"connected": false, "configured": false, "connect_path": "/mcp/google/connect"}` (plus `scopes`, `expires_at`, `has_refresh_token` when a token row exists) — `connected` reflects a stored, non-expired (or refreshable) token; `configured` says whether the OAuth client env vars exist at all, so the **Settings → Connectors** card can explain an unconfigured server instead of offering a connect button that would dead-end on the connect route's honest 503. Free; used by the frontend/ops to check the connector before promising doc creation. Never returns token values.

### AI recaption (added 2026-10-25)

Direct REST path to the caption-repurpose pipeline for the **webapp composer's auto AI-recaption** (the chat UI keeps using the `repurpose_caption` agent tool; both consume the same DB-free core in `legacy/app/services/repurpose_flow.py`). Runs the requested platforms **concurrently** (pure LLM fan-out, one read session + one batched write session), so a 4-platform recaption costs roughly one platform's wall time.

#### `POST /repurpose`

**Request body:**

```json
{
  "source_text": "we shipped the new builder tonight",
  "platforms": ["twitter", "linkedin", "bluesky", "instagram"],
  "profile_id": null,
  "must_keep_phrases": ["v2.0"]
}
```

- `source_text` (required): 1–8000 chars, stripped; blank → `422`.
- `platforms` (required): 1–8 ids, deduped case-insensitively. Supported: `twitter, x, linkedin, tiktok, instagram, bluesky, farcaster, facebook, youtube`. Unknown id → `422` naming it (never silently aliased).
- `profile_id` (optional): defaults to the first (seeded) profile; unknown id → `404`.
- Alias map (rule set applied): `twitter/bluesky/farcaster → x`, `facebook → instagram`, `youtube → linkedin`, `linkedin/tiktok/instagram` native.

**Response:**

```json
{
  "profile_id": 1,
  "results": [
    {
      "platform": "twitter",
      "rule_platform": "x",
      "ok": true,
      "attempt_id": 42,
      "request_id": 30,
      "output": "shipped the new builder tonight. no fanfare, just…",
      "changes": [{ "change": "restructured", "reason": "platform rule" }],
      "must_keep_passed": true,
      "judge_verdict": "yes",
      "judge_confidence": 0.91,
      "route_label": "standard",
      "fallback": false,
      "error": null
    }
  ],
  "elapsed_ms": 8421
}
```

**Notes:**
- `platform` echoes the requested id; `rule_platform` is the rule set that actually ran.
- Per-platform failures are honest `ok: false, error: "..."` entries — one broken platform never discards the others, and only successes are persisted (`repurpose_requests` + `repurpose_attempts`, one request row per platform, single commit).
- `fallback: true` means the generator returned the source unchanged (LLM outage passthrough) — clients must not present it as a generated recaption.
- Same demo posture as every route here: **no auth**, CORS `*`. Costs Groq + Jev/TypeSafe calls only — **0 Xpoz credits**.

---

## What is NOT an endpoint

Everything else is a tool the agent calls internally:

- Backfilling posts → `connect_account` tool
- Extracting voice profile → `extract_voice_profile` tool
- Repurposing captions inside chat → `repurpose_caption` tool (same pipeline as `POST /repurpose`, which the webapp composer calls directly)
- Starting/stopping listening → `start_listening` / `stop_listening` tools
- Checking trending posts → `check_trending` tool
- Logging user actions → `submit_action` tool
- Recording handles the user pasted for lookup → `save_user_request` tool (stores them as user requests, never as peers; searching them is `check_niche_trends`)
- Google Drive/Docs operations (list files, create a doc, …) → dynamically registered `mcp__gdrive__*` / `mcp__gdocs__*` tools (MCP discovery; write verbs are gated behind explicit user confirmation — see `docs/mcp-connectors.md`)

These run inside the agent loop, triggered by the user's chat messages, not by direct HTTP calls from the frontend.

All tools operate on X (Twitter) data only. The `platform` field on repurpose attempts is always `x` in the MVP.