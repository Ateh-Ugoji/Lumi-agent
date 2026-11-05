# MCP connectors (Google Drive + Docs first)

> Lumi runs **its own MCP client**. Anthropic's cloud-side MCP connector only exists on
> Anthropic's API; this agent runs on Groq/OpenRouter behind the OpenAI SDK, so connector
> tools are discovered over MCP (Streamable HTTP) and converted to OpenAI-style function
> specs for the same tool-calling loop. That means: no provider switch, no Anthropic key,
> and localhost/stdio servers are supported later (a cloud-side connector can never reach them).

Status: **landed 2026-10-21** — registry + OAuth + client + confirmation gate + `#doc`
composer trigger; Google consent blocked on the manual GCP setup below (checklist, §3).

---

## 1. Architecture (who does what)

| Piece | File | Role |
|---|---|---|
| Connector registry | `legacy/app/services/mcp_connectors.py` | **Config**: name, server URL, auth method, scopes, tool allowlist, write-confirmation flag. Adding a connector = one entry here. |
| MCP client | `legacy/app/services/mcp.py` | `tools/list` discovery (cached `MCP_TOOLS_TTL` 300s), OpenAI-spec conversion, `tools/call` dispatch, Google token refresh, **write-confirmation gate**. |
| OAuth routes | `legacy/app/routers/mcp_google.py` | `GET /mcp/google/connect` → Google consent (offline + forced consent); `GET /mcp/google/callback` → code→token exchange into DB; `GET /mcp/google/status`. |
| Token store | `legacy/app/models/mcp_auth_account.py` (table `mcp_auth_accounts`) | One row per auth account (`google`), access + refresh tokens, expiry, granted scopes. Migration `e4f1a2b3c5d6`. |
| Toolset merge | `legacy/app/tools/registry.py` | `list_tool_specs()` appends cached `mcp__<connector>__<tool>` specs; `call_tool()` routes `mcp__*` names to the MCP client. |
| Turn wiring | `legacy/app/agent/loop.py` | Per turn: TTL-gated discovery refresh (best-effort, never raises) → before the model speaks, resolves a pending write from the previous turn (execute on a clear yes, cancel otherwise) and injects the **real outcome** as a system note. |
| Prompt | `legacy/app/agent/prompts.py` rule 16 | Plain-language routing ("make a doc" → connector tools) + the confirmation protocol + "say Google isn't connected" when `mcp__*` tools are absent. |
| Composer | `frontend/.../PromptBar.tsx` | `#` menu: `#doc` / `#drive` prefills an editable prompt (never auto-sends). |

Flow per connector:

1. **Discovery** — on each agent turn (rate-limited to once per 300s per connector), open a
   Streamable-HTTP session, `tools/list`, convert each tool to an OpenAI function spec named
   `mcp__<connector>__<tool>` (sanitized to `[A-Za-z0-9_-]`; the original name is kept for
   the call and restored on dispatch). Filtered by the connector's `allowed_tools`.
   No token / unreachable / disabled → the connector simply contributes no tools this turn;
   the model then honestly says Google isn't connected (gate-covered).
2. **Dispatch** — the loop's existing `registry.call_tool` path routes `mcp__*` to
   `legacy/app/services/mcp.py`, under its own `MCP_CALL_TIMEOUT_SECONDS` (60s) inside the loop's
   120s per-tool cap. Results are `{tool, content}` or `{error}` — failures are honest
   error payloads, never raised out of the turn.
3. **Write gate** — a tool whose name contains a write verb (`create/update/delete/...`,
   word-wise match so `get_file_created_time` is NOT gated) stops at
   `confirmation_required`: nothing runs, the model tells the user what will run and asks.
   The user's next message resolves it: a clear yes (no defer words like "but/wait/later")
   executes and injects the real outcome; anything else cancels. There is never a stale
   pending write.

## 2. Google endpoints & scopes (verified, not guessed)

Official Google MCP servers (Streamable HTTP):

| Connector | Server URL | Scopes |
|---|---|---|
| `gdrive` | `https://drivemcp.googleapis.com/mcp/v1` | `auth/drive.readonly` + `auth/drive.file` |
| `gdocs` | `https://docsmcp.googleapis.com/mcp/v1` | `auth/documents` |

Both are reached with **one** Google token whose scope set is the union (one consent
unlocks both). `drive.file` is deliberately the *narrow* write scope: it only covers files
**this app creates**, so even a confirmed write cannot touch the user's other files.
Enable in the GCP project: `drive.googleapis.com`, `drivemcp.googleapis.com`,
`docsmcp.googleapis.com`.

## 3. Manual Google Cloud setup checklist (one time)

1. Create/choose a GCP project → **APIs & Services → Library**: enable
   `drive.googleapis.com`, `drivemcp.googleapis.com`, `docsmcp.googleapis.com`.
2. **OAuth consent screen**: External → add scopes above → add yourself as a **test user**.
3. **Credentials → Create → OAuth client ID → Web application**, and enable
   **"Use this client for an AI-powered agent"** (required for the MCP servers).
4. Add the redirect URI exactly matching the local (or deployed) callback:
   `http://localhost:8000/mcp/google/callback` (prod: your Railway domain + `/mcp/google/callback`).
5. Put in `.env` (gitignored — names only in docs): `GOOGLE_OAUTH_CLIENT_ID`,
   `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`.
6. Visit `http://localhost:8000/mcp/google/connect` once and accept → tokens land in
   `mcp_auth_accounts`; refresh is automatic (`access_type=offline` + `prompt=consent` were
   requested so a refresh token exists).
7. Verify: `GET /mcp/google/status` → `"connected": true`. The same response
   carries `"configured"` (are the OAuth client env vars set at all?) — the
   frontend's **Settings → Connectors** card reads it, so an unconfigured
   server explains itself instead of offering a dead connect button.

Without client config, `/mcp/google/connect` answers an honest **503**
(`google_oauth_not_configured`) — it never fabricates a consent URL.

## 4. Live verification script (after §3)

Zero-cost parts (no LLM, no credits):

```
GET /health                 -> {"status":"ok"}
GET /mcp/google/status      -> {"connected": false, "configured": true/false, ...}
                               (connected: true after consent; configured: false = OAuth client env vars unset)
GET /mcp/google/connect     -> 503 until configured, then 302 to accounts.google.com
```

End-to-end (uses the LLM on Groq, reads Drive only):

```
POST /chat   {"profile_id": 1, "message": "List my 5 most recently modified Drive files"}
```

Expected: `tool_calls_made` contains `mcp__gdrive__…`, the reply lists five real files
(honest empty/`no files` if the Drive is empty). The write path:

```
POST /chat   {"profile_id": 1, "message": "make a doc about my week"}
```

Expected: model calls `mcp__gdocs__create_…` → `confirmation_required` → model asks you to
confirm → `POST /chat {"message": "yes"}` → system note carries the **real** outcome →
model reports it. `no` / `yes, but later` → cancelled, nothing runs.

## 5. Adding another connector (config, not code)

1. Add one entry to `CONNECTORS` in `legacy/app/services/mcp_connectors.py`:

```python
MCPConnector(
    name="notion",                                  # tools become mcp__notion__*
    url="https://mcp.notion.com/mcp",               # verified Streamable-HTTP URL
    auth="bearer_env",                              # google_oauth | bearer_env | none
    bearer_env="NOTION_MCP_TOKEN",                  # bearer_env only: env var name
    scopes=(),                                     # google_oauth only
    enabled_env="MCP_NOTION_ENABLED",              # optional kill-switch env (default on)
    allowed_tools=("search", "fetch_page"),        # None = expose everything
    confirm_writes=True,                           # gate write/edit/delete behind yes
),
```

2. Put the credential in `.env` (for `bearer_env`) — **or** implement another auth method in
   `legacy/app/services/mcp.py:_auth_headers` / `_auth_ready` if the server needs something new.
3. Restart. No router, no loop, no prompt changes: discovery, spec merge, dispatch, timeouts
   and the write-confirmation gate all key off the config.

Rules that stay true for every connector: specs are namespaced (`mcp__<name>__<tool>`),
allowlist filters at discovery time, `confirm_writes=False` only for read-only servers, and
**tokens/secrets never appear in code, docs, logs, or chat output** (env var names only).

## 6. Config reference (env names only)

| Env var | Default | Meaning |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | empty | Google OAuth web client (§3); empty ⇒ `/mcp/google/connect` → 503 |
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:8000/mcp/google/callback` | must match a registered redirect URI |
| `MCP_ENABLED` | `true` | master switch for every connector |
| `MCP_GDRIVE_ENABLED` / `MCP_GDOCS_ENABLED` | `true` | per-connector kill switch |
| `MCP_TOOLS_TTL_SECONDS` | `300` | discovery cache per connector |
| `MCP_REFRESH_TIMEOUT_SECONDS` | `15` | per-turn discovery budget |
| `MCP_CALL_TIMEOUT_SECONDS` | `60` | single `tools/call` budget (loop caps the turn at 120s) |

## 7. Tests

- `legacy/tests/test_mcp.py` — spec conversion/allowlist, caching + master switch, read dispatch,
  confirmation gate (require → yes / no / defer / failure), registry routing, discovery
  against a faked MCP session, Google refresh/persistence. Every network seam patched.
- `legacy/tests/test_mcp_google_router.py` — three routes, 503 not-configured, consent URL
  components (offline + consent + scope union + state), callback exchange/state/denial.
- `legacy/tests/test_agent_claim_gate.py` — doc-flow gate regressions + the confirmed/declined
  turn tests (real outcome note, TOOL row, `tool_calls_made`).

No test opens a real socket: `_open_session`, `_execute_remote`, `_post_token_exchange`
are the three seams.
