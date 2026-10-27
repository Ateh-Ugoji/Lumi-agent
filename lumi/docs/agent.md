# Agent

`app/agent/` — the chat loop, persona prompt, and LLM plumbing.

## `loop.py` — the actual loop

`run_agent_loop(profile_id, user_message)`:

1. Save the user message, load prior history, prepend the system prompt (persona + operating rules + per-request profile context). Also: refresh the MCP connector toolset (TTL-gated discovery, best-effort — never raises) and, if the previous turn left a pending write-confirmation, resolve it from this message first (clear yes → run the tool and carry its **real** outcome into the context as a system note; anything else → cancel note).
2. **Trim the request to the token budget** before every completion: `MAX_REQUEST_TOKENS = 6_700` estimated whole-request tokens (chars ÷ 3.5, system prompt + history + current ask + tool specs). Ladder while over budget: drop oldest history → shrink older tool-group results to ≤1,200 chars → drop the oldest whole tool-group — never the system prompt, the current ask, or the newest tool group. Re-checked every loop iteration because tool results grow the transcript mid-turn; still-over is sent with a warning log (Groq's second model, ~8k-token wall, is the backstop). Each tool result's in-context copy is separately capped at `TOOL_CONTEXT_CHAR_LIMIT = 4000` chars — the full text stays in the DB. (Why: qwen's ~7,000-token input wall 413'd loaded turns before this landed.)
3. Call the LLM with the full tool registry available (native tools + any authenticated connectors' `mcp__*` tools) — inside the provider chain below, which falls through models then providers on any `APIError`.
4. If it didn't request a tool call, save the reply and return (after the action-claim gate, which nudges once and disclaims if a zero-tool reply claims work it didn't do).
5. If it did, save an assistant message carrying the raw `tool_calls` JSON, execute each tool call (120s timeout each; failures become honest error messages fed back to the model), save each result as a `role=tool` message, and loop back to step 3.
6. Hard-capped at `MAX_TOOL_ITERATIONS = 6` — if the model keeps calling tools past that, it gets a canned "try rephrasing" reply instead of looping forever.

Every message (user, assistant, tool) is persisted **immediately**, not batched at the end — so a crash mid-loop still leaves a readable history. `tool_calls_made` accumulates tool *names* across the whole loop and is what `POST /chat` returns to the frontend.

**Greeting gate:** `is_greeting_only(message)` whitelists short greeting phrases ("hi", "hello", …). Those turns run with **no tools** (`tools=[]`) and no tool-enabled completion — the model just replies conversationally, so a "hi" can never trigger backfills or extraction.

`tool_executions` (list of `{name, arguments, sample_posts, result}`) is also returned and streamed to the frontend. For `get_analytics` the raw `result` dict is included so the insight card can render real numbers.

### Profile context injection (anti-fabrication)

At the start of `_agent_turn`, the loop loads the active `Profile` and sets a `ContextVar` (`_current_profile_id`). The registry wraps every tool call so a missing or `None` `profile_id` argument is auto-filled from that context. The system prompt ends with a `CURRENT PROFILE CONTEXT` block (id, handle, name) so the model never has to guess the profile id — and if it still passes a wrong id, tools raise "Profile N not found" and the prompt tells it to retry with the context id.

`get_analytics`'s schema no longer marks `profile_id` as required (the context injects it), which stops the model from inventing ids when the param is optional-looking.

## `providers.py` — OpenLux, then Groq, then OpenRouter

All providers are OpenAI-compatible, so each is the same `AsyncOpenAI` client at a different `base_url`. `get_providers()` is a **lazy singleton** — first call does `neatlogs.init()` and builds+wraps the clients once; every call after that reuses them. Chain order: **OpenLux** (`qwen3.8-27b` via `OPENLUX_MODEL`, included only when `OPENLUX_API_KEY` is set) → **Groq** (`qwen/qwen3.8-27b`, then `openai/gpt-oss-120b`) → **OpenRouter** (`meta-llama/llama-3.3-70b-instruct`). Groq carries **two models in chain**: qwen has a measured ~7,000-input-token request wall (413 above it), gpt-oss-120b ~8,000 with tool-calling verified — so a qwen 413/429 from a tool-heavy or over-budget turn is retried on the second Groq model **before** the chain moves to OpenRouter.

`chat_completion_with_provider(messages, tools, model=None)` tries **each model within a provider, then the next provider**, on any `openai.APIError`, logging `provider X model Y failed, trying next model|next provider` (plus a `neatlogs.log` event carrying the model name). If all fail, it raises `RuntimeError("all LLM providers failed")`. It returns `(completion, provider_name)`. `chat_completion_with_fallback` is the same call without the provider name, and is what the agent loop uses.

Passing `model=` pins a single model per provider — repurpose tiering relies on this ("small" must never be silently upgraded to a big model). **Check each provider's live model catalog before changing an ID** — Groq has dropped models before (all its Llama chat models are gone).

**Don't instantiate `AsyncOpenAI(...)` anywhere else in the codebase.** Going through `get_providers()` is what keeps tracing and fallback centralized — a second ad-hoc client would be untraced and wouldn't fall back. One documented exception exists: `get_audio_provider()` (plain Groq client for the voice-transcribe STT call, which rides `audio.*`, not chat completions).

## `prompts.py` — persona-first system prompt

`build_system_prompt(profile_id, handle, name)` returns the persona block (the user's own voice/writing/honesty/safety/agent-behavior rules), then appends:

- **Operating rules** — no em dashes; never invent URLs (use `[Connect X](<url>)` or omit the link); use the exact `profile_id` from `CURRENT PROFILE CONTEXT`; if a tool says "Profile N not found", retry with the context id; call `get_analytics` immediately when asked for stats; if no voice profile exists, call `extract_voice_profile` (not `connect_account`). Rules 13–15 cover pasted-handle lookups and honest labeling; **rule 16** covers MCP connectors: plain-language routing ("make a doc" → the Google tools, matching the composer's `#doc`/`#drive` prefills), the write-confirmation protocol (never claim a write happened before the user confirms; report the real outcome after), and "if no `mcp__*` tools are in your toolset, say Google isn't connected". **Rules 17–20** (2026-10-25, the coverage fix): per-handle coverage line before any recon answer ("full picture" only when every named handle was scanned), stored frameworks usable as evidence only when the account is in their `source_handles`, no invented numbers/locations/dates (placeholder or ask; use today's date — `build_system_prompt` injects `- today's date: … (UTC)` into `CURRENT PROFILE CONTEXT`), and state whose account an ambiguous deliverable is for.
- **`CURRENT PROFILE CONTEXT`** — `profile_id`, `handle`, `name` for this request.

`connect_account` tool descriptions reference this prompt: they return `already_connected` for the seeded account and a real `[Connect X](<url>)` string for new connects — no example.com or fabricated URLs.
