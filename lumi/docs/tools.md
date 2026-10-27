# Tools

`app/tools/` — the functions the LLM can call during the chat loop. Registration happens via a decorator, but the decorator only runs if the module is imported.

## Registration

`registry.py` holds a module-level dict. `@tool(name, description, parameters)` wraps a function and adds it to that dict at **import time**. `app/tools/__init__.py` imports every tool module for that side effect (20 tools currently):

```python
from app.tools import actions, advice, activity, analytics, backfill, connect, listening, memory, posts, repurpose, user_requests, voice
```

**Adding a new tool means adding its module to that import list too** — the decorator alone does nothing if the module is never imported. `list_tool_specs()` turns the registry into the OpenAI `tools=[...]` payload; `call_tool(name, arguments)` dispatches a parsed tool call to the matching function. The registry auto-fills a missing `profile_id` from the request context (`CURRENT PROFILE CONTEXT` in the prompt).

## MCP connector tools (dynamic — not in this registry)

`mcp__<connector>__<tool>` functions (Google Drive/Docs first) come from the **connector registry** (`services/mcp_connectors.py`), not from the `@tool` decorator: each agent turn, `services/mcp.py` refreshes a per-connector `tools/list` cache (TTL 300s) and `list_tool_specs()` appends the converted specs; `call_tool()` routes `mcp__*` names into `services/mcp.py` (bearer token from `mcp_auth_accounts`, auto-refreshed; 60s timeout; honest `{error}` payloads — never a raised 500). Tools whose names contain a write verb stop at the **confirmation gate** — nothing runs until the user's next message clearly confirms. No token / server down / disabled → the connector simply contributes no tools that turn. Adding another connector is a config entry, not code: `docs/mcp-connectors.md`.

## Content routing (posts vs user_activity)

`classify_post_kind(caption)` (`services/pfm.py`) runs in **all three ingestion paths** (shared `backfill_profile_posts`, analytics `_ingest_pfm_feed`, analytics `_ingest_xpoz_user_posts`):

- **original** (incl. quote tweets) → `posts` — voice extraction, captions/repurpose, analytics.
- **reply** (`@`-opener) → `user_activity` — the user's own words; feeds `get_user_activity` and the voice profile's `reply_style` field.
- **retweet** (`RT`/`RT @`/`RT:` opener) → `user_activity` — content the user shared, never attributed to them, never voice material.

PFM/X expose no structural reply/RT flags (verified in their OpenAPI spec), hence the text heuristics. Defense in depth: extraction filters posts again before the min-count check, and the Chroma corpus upsert skips non-authentic captions.

## Per-tool notes

- **`connect.py` — `connect_account(handle)`**: does **not** touch the database. It only calls Post for Me's `auth-url` endpoint and returns a `connect_url` for the agent to hand the user — the actual `Profile` row gets created later, by `GET /pfm/callback` (see `routers.md`), once the user finishes the OAuth flow in their browser. `pfm_account_id` is required+unique at the DB level, so a profile genuinely can't exist before that completes.
- **`backfill.py` — `backfill_posts(profile_id)`**: on-demand pull of a profile's posts + metrics from PFM via `backfill_profile_posts` (`services.md`); originals land in `posts`, replies/RTs route to `user_activity`. Returns an error dict if the profile has no linked PFM account or `PFM_JWT_TOKEN` is missing.
- **`voice.py`**: `extract_voice_profile` needs ≥5 authentic posts. If the profile has fewer, it tries a PFM backfill first, and only then returns `needs_style_questions: True` instead of failing. Recent `user_activity` replies are passed to the extractor and feed the `reply_style` field only — never the main voice fields (retweets are never used at all). Chroma corpus provides a diverse sample (fallback `posts[:10]`). See `models.md` for the versioning/flush gotcha it relies on. `get_voice_profile` returns the current version; `answer_style_questions` is a plain insert — no versioning concept, unlike voice profiles.
- **`activity.py` — `get_user_activity(profile_id, kind="all", limit=15)`**: newest-first slice of `user_activity`. The tool description tells the model: replies are the user's own words; retweets are shared content and must never be attributed to the user — use for "since you said X…" conversational depth.
- **`listening.py`**:
  - `start_listening`/`stop_listening` just toggle `poll_config.is_active`.
  - `check_trending` is the spike-detection + alert-write logic for the profile's **own** posts — called both by the background poller and (via chat) on demand. Inert in practice until a metrics-refresh pass exists (needs ≥2 snapshots per post).
  - `check_niche_trends(profile_id, handles, min_likes=50)` pulls recent tweets from other accounts via Xpoz and writes the ones over `min_likes` into `listening_matches` (deduped by `platform_post_id`). On-demand only — not in the poller, and it doesn't set `alerted_at`. It also feeds the shared handle DB (`app/services/handle_db.py` → the @-bar's Chroma `handle_mappings`): every tracked account (bounded enrichment: picture/name/followers for genuinely-new handles) and every author of every returned post, `origin: niche` — best-effort, never fails the scan. Right after saving, it reads each author's picture back from that store onto the match row (`listening_matches.author_avatar_url`; NULL when the store doesn't know the face) so ChronicOnline, the thinking cards and the handle DB show the same face — unavatar stays the client-side fallback.
  - `discover_and_extract_niche_frameworks(profile_id, query)` runs an Xpoz keyword search purely for **discovery** (which accounts to read), persists every search-result author to the shared handle DB first (handle-only — authors are unbounded, picture enrichment stays capped to scanned accounts), then runs `app/services/peer_pipeline.py` on those handles: ~60 posts per account, 28-day per-account baseline, winners at ≥1.5× the account's own median, blind LLM tagging (text only, cached by `post_id`+`prompt_version`), lift table, synthesis. Persists `niche_framework_reports` + `post_taggings` and bridges the report into `peer_frameworks` + Chroma. Every result carries `report_status` (`ok` / `insufficient_data` / `failed`) — a run with nothing to report names no frameworks instead of inventing them (the old canned fallback is deleted).
- **`advice.py` — `get_peer_advice`**: retrieval-first over Chroma (`peer_frameworks` + `peer_posts`); empty store → one live peer-pipeline run (`discover_and_extract_niche_frameworks`) → re-query; everything failed → honest `found: false` + reason.
- **`memory.py` — `remember` / `recall_memory`**: durable facts in Chroma `agent_memory` (deduped; semantic recall bumps access metadata). Chroma down → honest `stored/ found: false` + `reason: chroma_unavailable`.
- **`analytics.py` — `get_analytics(profile_id)`**: real aggregated numbers from `posts` ⋈ `metric_snapshots` (paired by `post_id`); zero posts → opportunistic backfill (routes replies/RTs to `user_activity`). No data → honest zeros + `is_live_data: false` — never demo numbers.
- **`repurpose.py` — `repurpose_caption(profile_id, platform="x", post_id=None, source_text=None, must_keep_phrases=None)`**: takes either a tracked post or raw text; creates the `RepurposeRequest` then the `RepurposeAttempt` in one call (no separate "create a request" step). Flow: LLM rewrite per-platform rules → deterministic `enforce()` (280-char X limit + must-keep phrases, JSON-string phrases normalized) → Jev/TypeSafe semantic judge (auto-retry once on low confidence). LLM failure → passthrough of the source text (flagged only by `changes[0].reason == "Fallback mode"`). Does **not** clear alerts — only `dismiss_alert` does. Note: `route_label` is never set, and `platform` on the attempt row keeps its default.
- **`actions.py`**: `submit_action` logs a decision against an attempt. `dismiss_alert` takes a `post_id` (not a request/attempt id) — it flips `Post.alert_dismissed` only, leaves `alerted_at` untouched. If the post is still spiking next time `check_trending` runs, it re-alerts with a fresh `alerted_at` — alert-once-per-episode, not alert-once-forever.
- **`posts.py` — `get_posts`**: simple `limit`-based listing of authentic posts, newest first. No cursor pagination (fine at demo data volumes).
