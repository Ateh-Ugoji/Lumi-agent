# Frontend integration

Everything you need to wire a frontend up to this backend. Verified against the live deployment, not just the spec — see "Current status" at the bottom for what actually works today.

## Base URL

```
https://lumi-api-production-6260.up.railway.app
```

This is the Railway-generated domain for the `lumi-api` service — yes, whatever Railway deploys *is* what the frontend talks to. There's no separate "public API" layer; the FastAPI app you'd run locally with `uvicorn app.main:app` is the exact same app running behind this URL.

For local development against a locally-running backend, use `http://localhost:8000` instead (`uv run uvicorn app.main:app --reload` from the backend repo).

## Auth

None. No login, no API key, no session token. Every request just needs a `profile_id` — there's no concept of "which user is making this request" beyond that.

## CORS

Wide open (`allow_origins=["*"]`) — call it from anywhere, no preflight config needed on your end.

## The five endpoints

Almost everything goes through `POST /chat`. The other four exist only for UI state the chat loop doesn't cover — don't expect (or ask for) more REST endpoints; new functionality is almost always meant to be a chat message, not a new route.

### `POST /chat`

The agent loop entry point.

```json
// Request
{ "profile_id": 1, "message": "What's trending right now?" }

// Response
{ "role": "assistant", "content": "...", "tool_calls_made": ["check_trending"] }
```

- `tool_calls_made` is the list of internal tool names the agent invoked while producing this reply (useful for debug UI, not required to render).
- **Latency will be high (seconds, not milliseconds)** — it's a chained LLM call, possibly multiple tool calls in sequence. Show a loading state.
- Errors as a plain `500` with no JSON body on provider failure (see "Current status" — this is the current behavior until real LLM keys are configured, not something to special-case forever).

### `GET /chat/history?profile_id=1&limit=50&before=<message_id>`

Loads prior conversation, newest-`limit` first then returned in chronological order.

```json
{
  "messages": [
    { "id": 1, "role": "user", "content": "...", "created_at": "2026-10-10T20:00:00Z" },
    { "id": 2, "role": "assistant", "content": "...", "created_at": "2026-10-10T20:00:03Z" }
  ]
}
```

- `role` is always `"user"` or `"assistant"` here — internal `"tool"` messages are filtered out server-side. You're not meant to render raw tool-call JSON as a chat bubble.
- `before` is a cursor: pass the `id` of the oldest message you currently have to load the next page back.

### `GET /profiles`

For a profile switcher.

```json
{
  "profiles": [
    { "id": 1, "name": "Lumi Demo Creator", "platform": "x", "handle": "lumi_demo_creator", "has_voice_profile": false, "listening_active": false }
  ]
}
```

### `POST /profiles/{id}/select`

Call this when the user switches profiles. **It's UI-only** — there's no server-side session, nothing is mutated, it just hands back a state snapshot so you don't need three separate calls to know whether to show "no voice profile yet" / post count / listening status.

```json
{ "profile_id": 1, "name": "Lumi Demo Creator", "voice_profile_exists": false, "post_count": 0, "listening_active": false }
```

### `GET /profiles/{id}/alerts/unread`

Poll this every 5–10 seconds to drive toast notifications ("this post is trending").

```json
{
  "alerts": [
    {
      "post_id": 17,
      "caption": "...",
      "platform_post_id": "abc123",
      "alerted_at": "2026-10-10T14:30:00Z",
      "velocity": { "likes_per_hour": 45.0, "baseline_likes_per_hour": 12.0 }
    }
  ]
}
```

Will currently always return `{"alerts": []}` — see "Current status."

## Connecting an X account — not a REST call, a redirect

There's no "connect account" endpoint to call directly. The flow is agent-driven:

1. User tells the agent (via `POST /chat`) they want to connect their X account.
2. The agent calls the `connect_account` tool internally, which comes back as a `connect_url` inside that tool's result — surfaced to you only via the chat response's `content` (the agent will include the link in its reply text) or `tool_calls_made` (confirms the tool ran, but doesn't carry the URL itself — read the `content` for the actual link).
3. **Open that URL** — it's a real OAuth redirect to X's login page, not something you can embed as an API call.
4. The user authorizes, and Post for Me redirects their browser to our backend's `/pfm/callback`, not back to you.

**Known gap, affects your UX design:** `/pfm/callback` currently returns a bare JSON response (`{"connected": true, "profiles": [...]}`) — there's no redirect back into your app yet. A real user finishing the OAuth flow today lands on a blank JSON page, not back in your UI. Worth syncing with backend on this before building the "connect account" flow — it may redirect back to a URL you specify, or you may need to poll `GET /profiles` afterward to detect the new connection. Not decided yet.

## Current status (verified against the live deployment just now)

| Endpoint | Status |
|---|---|
| `GET /health` | ✅ Works |
| `GET /profiles` | ✅ Works, returns real seeded data |
| `POST /profiles/{id}/select` | ✅ Works |
| `GET /chat/history` | ✅ Works (empty until there's history) |
| `GET /profiles/{id}/alerts/unread` | ✅ Works, but **always empty** — no metrics ingestion pipeline exists yet, so nothing can ever be flagged as trending. Not a frontend bug if you see an empty list forever. |
| `POST /chat` | ⚠️ Currently **500s on every call** — `GROQ_API_KEY`/`OPENROUTER_API_KEY` are placeholder values on the deployed service, so every LLM call fails. Build your UI against the documented shape; it'll start actually working once real keys are set. |

If you're integrating *today*, you can fully build and test the profile switcher, chat history rendering, and alert polling UI against real responses. Chat itself will need real LLM credentials in place before you can see an actual reply.
