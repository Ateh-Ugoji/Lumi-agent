# Routers

`app/routers/` — eight files. `chat.py`, `profiles.py`, and `alerts.py` match `.agents/api-endpoints.md` and exist only for what the frontend needs outside the chat loop; everything else is an agent tool (`tools.md`). Don't add a new router for something that could be a tool call instead. `pfm.py` and `mcp_google.py` are different — they're not really frontend-facing endpoints, see below. `trends.py` and `voice.py` are thin HTTP wrappers over existing tool/service code (see `.agents/api-endpoints.md`); `handles.py` is a pure delegation shim — see its section at the bottom.

## `chat.py`

- `POST /chat` — runs the agent loop, returns `{role, content, tool_calls_made, tool_executions}`. All the actual work happens in `app/agent/loop.py`; this is a one-line pass-through.
- `POST /chat/stream` — same request body, but returns server-sent events while the loop runs: `tool_start` and `tool_done` as each tool executes, then `done` (final `content` + `tool_executions`) or `error`. Use this when the UI should show tool progress live.
- `GET /chat/history` — cursor-paginated by message `id` (`before` + `limit`, default 50), **filters out `ChatRole.TOOL` messages** — the frontend renders user/assistant turns, not raw tool JSON. If you need tool-call visibility in the UI later, that filter is the place to loosen.

## `profiles.py`

- `GET /profiles` and `POST /profiles/{id}/select` both compute `has_voice_profile`/`listening_active` (and `post_count` for `/select`) with small per-profile helper queries — N+1, but fine at 3-profile MVP scale.
- `/select` is **UI-only**. There's no server-side "active profile" session concept — it just returns a state snapshot for the frontend to cache client-side. Calling it doesn't mutate anything.

## `alerts.py`

- `GET /profiles/{id}/alerts/unread` queries `posts` directly (`alerted_at IS NOT NULL AND alert_dismissed = false`), then computes `velocity` per post from its `metric_snapshots` via `services.metrics.current_and_baseline_velocity`. No caching — recomputed live on every request, so the number shown isn't a snapshot of what triggered the alert, it's whatever the current data says. Frontend is expected to poll this every 5–10s. Only covers the profile's own `posts` — Xpoz `listening_matches` aren't surfaced here yet. Stays empty until real PFM accounts are connected and backfilled (see `background.md`).

## `pfm.py` — not a frontend endpoint

- `GET /pfm/callback` is where **Post for Me** redirects the user's browser after they complete (or abandon) connecting an X account — see `tools.md`'s `connect_account` entry and `.agents/external-services.md` for the full flow. It reads `isSuccess`/`accountIds`/`error` off the query string and is where a `Profile` row actually gets created (or updated, if `pfm_account_id` already exists — a reconnect).
- This URL has to be registered in the Post for Me project dashboard — it can't be set per-request via the API when using PFM's system credentials. Nothing calls this route directly; it only exists because PFM redirects to it.

## `handles.py` — pure delegation to the handle-search MVP (added 2026-10-21)

- Four routes: `GET /handles/search`, `GET /handles/saved`, `POST /handles/select`, `GET /handles/stats`. **Zero business logic lives here** — every handler calls the corresponding function in `mvp/handle_search/server.py` (`api_search` / `api_saved` / `api_select` / `api_stats`), which stays the single source of truth for the cache→live ladder, the credit budget/kill-switch, the saved-vs-live mix, and the Chroma `handle_mappings`/`handle_cache` stores. Don't reimplement any of that here; extend the MVP core instead.
- Registered in `main.py` as the 7th router so the chat frontend (`PromptBar.tsx`'s `@` menu) talks to ONE API base — no second origin, no CORS on :8010. The standalone MVP bar at :8010 still runs its own copies of the same functions.
- Credits: only `/handles/search` can reach Xpoz (2/query, cache-first with prefix-chain reuse, `MVP_XPOZ_BUDGET` per session, `MVP_XPOZ_LIVE` kill-switch). A `q` under 2 chars returns `reason: "min_length"` with no external call. `/saved`, `/select`, `/stats` are free.
- Tests: `tests/test_handles_router.py` (route paths, delegation via monkeypatch, hermetic min-length path, app registration) + `tests/test_handle_search_mvp.py` (MVP core behavior, Xpoz fully mocked).

## `mcp_google.py` — OAuth only, not a tool endpoint (added 2026-10-21)

- Three routes: `GET /mcp/google/connect` (302 to Google consent, or an honest 503 `google_oauth_not_configured` when `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` are unset), `GET /mcp/google/callback` (code→token exchange into `mcp_auth_accounts`, upserted by auth account `"google"`), `GET /mcp/google/status` (`connected` / scopes / expiry / `configured` — the last flags whether the OAuth client env vars exist, consumed by the frontend's Settings → Connectors card).
- Like `pfm.py`, the callback returns JSON to the browser instead of redirecting into the SPA — a registered-redirect-URI + JSON landing page, same known UX gap as the PFM callback. The `state` is an in-memory single-use random (process memory: single-worker app, restart drops pending states — acceptable, the user just re-clicks connect).
- **No business logic here either** — token exchange and storage live in `app/services/mcp.py` (`_post_token_exchange`, `store_tokens`); this router only builds the consent URL and reads/writes the DB row. The MCP tools themselves are never HTTP endpoints — they're `mcp__*` function specs merged into the agent loop's toolset by `tools/registry.py` (see `docs/mcp-connectors.md`).
