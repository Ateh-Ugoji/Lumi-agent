# External Services

## Post for Me

Social media API for connecting social accounts, fetching posts/metrics, and publishing.

**Base URL:** `https://api.postforme.dev`

**Auth:** JWT bearer token. Stored as `PFM_JWT_TOKEN` env var. This is app-level, not per-user. Full OpenAPI spec: `https://api.postforme.dev/docs/json` (the `/docs` page itself is a JS-rendered Scalar UI; `/docs/json` returns the embedded spec directly).

**Rate limits:**
- 5 requests per second
- 40 requests per minute

### Confirmed endpoints

- **`POST /v1/social-accounts/auth-url`** — starts the OAuth connect flow. Body: `{platform, external_id, permissions: ["posts","feeds"], force_reauth?}`. Returns `{url, platform}` — redirect the end user there. **`feeds` must be requested or the account's post history/metrics are never accessible.** `external_id` is our own correlation value (we pass the handle); if an existing connection for that platform already has a *different* `external_id`, the reconnect attempt fails for that account instead of overwriting it.
- **Callback (not an API call we make — PFM redirects the user's browser here after auth):** query params `provider`, `projectId`, `isSuccess`, `accountIds` (comma-separated, on success), `failedAccountIds`, `error`. **The callback URL is configured in the Post for Me project dashboard, not via the API** — "Quickstart"/system-credential projects can't override it per-request. Someone with dashboard access needs to point it at `<deployed-app>/pfm/callback`.
- **`GET /v1/social-accounts/{id}`** — account details: `username`, `user_id`, `profile_photo_url`, `status` (connected/disconnected), `metadata.display_name`, plus the raw `access_token`/`refresh_token` (which we never store — see below).
- **`GET /v1/social-accounts`** — paginated list, filterable by `platform`, `username`, `external_id`, `id`, `status`.
- **`POST /v1/social-accounts/{id}/disconnect`** — revokes tokens, marks `disconnected`, keeps the record (reconnectable). Not wired into any tool yet.
- **`GET /v1/social-account-feeds/{social_account_id}`** — cursor-paginated (`limit`, `cursor`, not offset-based) post history for a connected account. Each item (`PlatformPostDto`) carries **both** `caption` and `metrics` in one response — this is the backfill endpoint *and* the metrics endpoint; they're the same call. For X, `metrics.public_metrics` has `like_count`, `reply_count`, `retweet_count`, `impression_count` → maps to our `metric_snapshots.{likes,comments,shares,views}` respectively.
- **`GET /v1/social-posts` / `GET /v1/social-posts/{id}`** — posts *we* create/manage through PFM (for publishing), not the account's organic post history. Not the right endpoint for backfill — use the feed endpoint above instead. Has `status` (draft/scheduled/processing/processed), suggesting a create/publish endpoint exists too (not yet needed or implemented on our side).

### The real connect flow

1. Call `create_auth_url` with `platform="x"`, `external_id=<handle>`, `permissions=["posts","feeds"]`.
2. Redirect the user to the returned `url`. They log into X and authorize — entirely on X/PFM's domain.
3. PFM redirects back to our registered callback with `accountIds` on success.
4. We call `get_social_account(id)` for each id to get real account details, then create/update the matching `Profile` row keyed by `pfm_account_id`.

**A profile cannot exist before step 4** — `pfm_account_id` is `NOT NULL` + unique, and it doesn't exist until the OAuth flow actually completes. There's no "pending" profile state; `connect_account` (the agent tool) only starts the flow and hands back a URL, it never touches the database. See `app/tools/connect.py` and `app/routers/pfm.py`.

### What Post for Me stores for us

Post for Me holds the OAuth tokens for each social account (`access_token`, `refresh_token`, expiry dates) — returned on the account-detail endpoints, but we never persist them. Our database only stores the `social_accounts[].id` from Post for Me as `pfm_account_id`.

### Platform scope

Post for Me supports Instagram, Twitter/X, LinkedIn, TikTok, TikTok Business, Facebook, YouTube, Pinterest, Bluesky, and Threads. **The MVP targets X (Twitter) only.** All three demo profiles are X accounts.

From the X-specific config (`TwitterConfigurationDto`), the relevant fields are:
- `caption` — the tweet text
- `reply_settings` — who can reply (following, mentionedUsers, subscribers, verified)
- `quote_tweet_id` — for quote tweets
- `poll` — duration and options (not needed for MVP)

For repurposing, we only use `caption`. The rest is available if the demo needs richer output.

### Data mapping to our schema

| Post for Me field | Source endpoint | Our database column | Notes |
|---|---|---|---|
| `social_accounts[].id` | account detail / callback | `profiles.pfm_account_id` | The link between our profile and PFM |
| `social_accounts[].platform` | account detail | `profiles.platform` | |
| `social_accounts[].username` | account detail | `profiles.handle` | |
| `social_accounts[].metadata.display_name` | account detail | `profiles.name` | Falls back to `username` if absent |
| `PlatformPostDto.platform_post_id` | account feed | `posts.platform_post_id` | PFM's platform-level post ID |
| `PlatformPostDto.caption` | account feed | `posts.caption` | |
| `PlatformPostDto.posted_at` | account feed | `posts.published_at` | |
| `metrics.public_metrics.like_count` | account feed | `metric_snapshots.likes` | |
| `metrics.public_metrics.reply_count` | account feed | `metric_snapshots.comments` | |
| `metrics.public_metrics.retweet_count` | account feed | `metric_snapshots.shares` | |
| `metrics.public_metrics.impression_count` | account feed | `metric_snapshots.views` | |

### Considerations

- **Posts and metrics come from one call, not two.** `GET /v1/social-account-feeds/{id}` returns both per post, paginated. A poll cycle is "1 (paginated) feed call per connected account," not one call per post.
- **Platform configurations could improve repurposing.** Each platform's DTO shows what fields exist (placement, privacy, tags, polls). The agent could use this to generate richer output than just a caption. Not for the MVP, but worth noting.
- **Post status tracking.** `/v1/social-posts` tracks `status` (draft → scheduled → processing → processed) for posts *we* publish through PFM. If we build publishing later, that's a stronger "was this actually posted" signal than our `user_actions` accept/reject.
- **Media handling.** Feed posts include media. The repurpose pipeline currently only handles captions. If a post's value is in its image or video, the repurposed caption without the media will be incomplete. Acknowledge this in the demo.

### Rate limit strategy

- Background polling runs every 5 minutes minimum per profile (`poll_config.interval_minutes`).
- A poll cycle for 3 profiles is 3 feed calls (paginated as needed) — not per-post, now that posts+metrics are confirmed to come from the same endpoint.
- If rate-limited (429), back off and retry on next cycle. Do not block the polling loop.
- MVP polls X accounts only. Three profiles, X platform only.

---

## Xpoz (social listening — broad market data, not our connected accounts)

Social media intelligence API — structured search/read access to X (and Instagram/Reddit/TikTok) content across the platform, not just accounts we've connected.

**Division of responsibility (confirmed):**
- **Post for Me** → the connected account's *own* posts. Powers voice extraction (`extract_voice_profile`) and, later, publishing. This is "what does this person sound like."
- **Xpoz** → broad social listening across X — trending content, competitors, the profile's niche generally. This is a *signal that informs what to write about*, not content the profile authored. It feeds `repurpose_caption` as input (a trending post worth reacting to, rewritten in the profile's own voice), not the voice extraction pipeline.

Those are genuinely different data shapes, not two sources for the same table — see "Schema" below.

**Auth:** Bearer access key (`Authorization: Bearer <key>`), created via the Xpoz dashboard or `POST /api/tokens`. Env var is `XPOZ_API_KEY` (already in `config.py`/`.env.example`, optional until this is built).

**Full OpenAPI spec:** `https://api.xpoz.ai/openapi.json` (the `/docs` pages are normal rendered docs, not JS-only like PFM's, but the spec is the fastest way to get the full picture).

### Recommended approach for v1 — keep it simple

Decided: don't use Xpoz's own tracking registry or keyword search for the first version. Use exactly **one endpoint**:

- **`GET /api/data/twitter/posts/users/{username}/live`** — fetch a public account's recent tweets, on demand, by username. No registration step, no config to keep in sync with a second system. Request a small page (last 10–20) with `?fields=id,text,authorUsername,likeCount,retweetCount,replyCount,quoteCount,impressionCount,createdAt` — response envelope is `{results: [...], count, has_more, next_page_cursor}`, same cursor shape as PFM's feed.

**Field mapping to `listening_matches` (confirmed, no gaps):**

| Xpoz field | `listening_matches` column |
|---|---|
| `id` | `platform_post_id` |
| `authorUsername` | `author_handle` |
| `text` | `caption` |
| `likeCount`, `retweetCount`, `replyCount`, `quoteCount`, `impressionCount` | `metrics` (JSON, dumped as-is) |
| *(not returned — build it)* | `platform_url` = `https://x.com/{authorUsername}/status/{id}` |

Explicitly **not** using, and why:
- `crawl/settings` (keyword/user tracking registry) — a second source of truth to keep in sync with our own DB for no real benefit when we can just fetch a known handle's timeline directly.
- `crawl/tweet` (per-tweet engagement over days) — a different feature (watching one post's metrics evolve), not "what's trending in this niche."
- `GET /api/data/twitter/posts/live` (keyword search) — more surface area (query syntax) than "watch a short list of niche accounts" needs.
- `GET /api/data/operations/{id}` (paginated-operation polling) — only needed for large paged requests; avoided by requesting a small page (e.g. last 10 tweets) per account per poll.

**Spike detection for this path should not reuse `metrics.py`'s velocity math as-is.** That logic diffs two `MetricSnapshot` rows over time, which assumes repeated polling of the *same* post — appropriate for the user's own posts (`posts`/`metric_snapshots`), not for someone else's tweet fetched once. For `listening_matches`, a simple **absolute engagement threshold on a single fetch** (`likeCount`/`retweetCount` above some bar) is enough, and far simpler than snapshotting history for third-party content.

**The threshold number itself is the one thing genuinely left open** — not an oversight, it depends on the tracked account's size/niche (100 likes is huge for a small account, nothing for a large one). Options, implementer's call: a flat starting number to tune later, or scaling it relative to the tracked account's typical engagement (would need a baseline, adding complexity back in — probably not worth it for v1).

### Full endpoint reference (not all of this is needed for v1)

- **`POST /api/crawl/settings`** — sets the caller's tracked keywords/users/subreddits/hashtags, **per platform** (`twitter`, `instagram`, `reddit`, `tiktok`). **This is a full replace, not an add** — body is the complete desired set; omitting an existing tracked item removes it. `GET /api/crawl/settings` reads the current config. Rejected with 403 if it exceeds the plan's tracked-item limit (`/api/extra-tracked-items` can buy more, prorated).
- **`POST /api/crawl/tweet`** — tracks a *specific* tweet's engagement over 1–30 days (default 7). Different from the above: this is "watch one post's metrics evolve," not "watch a keyword/user." Requires a `trackTweets` plan flag. `GET /api/crawl/tweet` lists your tracking requests (`id`, `status`, `endTime`).
- **`GET /api/data/twitter/posts/live`** — keyword/query search across X, live.
- **`GET /api/data/twitter/posts/users/{username}/live`** — a user's recent tweets, live (works for any public user, not just connected accounts).
- **`GET /api/data/twitter/posts/{id}/live`** — a single tweet by ID, live.
- **`GET /api/data/operations/{id}`** — poll a background operation for paginated (`responseType=paging`) requests; expires 15 min after completion.
- Equivalent `/api/data/{platform}/...` endpoints exist for Instagram, Reddit, and TikTok.

### How tracking actually surfaces data — **no webhooks, pull only**

There is no webhook, push, or dedicated "tracked results" endpoint anywhere in the spec (`/api/status/subscribe` is email notifications for *platform outages*, not content alerts). Even the one endpoint we're using has to be polled — Xpoz doesn't do spike/trend detection itself, it's a data source, not an alerting product. For how "is this trending" actually gets decided on this path, see "Recommended approach for v1" above (short answer: a simple threshold on a single fetch, not `metrics.py`'s velocity math).

### Schema — scaffold built, shape not final

`posts` stays exactly as-is: PFM-backfilled, `profile_id`-owned, powers voice extraction only. Xpoz results don't go there — they're not content the profile authored, and `posts.profile_id` is `NOT NULL` for exactly that reason (every row really is "this profile's own post").

A separate table, `listening_matches` (`app/models/listening.py`), holds Xpoz-sourced results. **This is a starting scaffold, not a fixed contract** — whoever implements the listening logic has more context on what the input/output actually looks like and should feel free to add/rename/drop columns to fit. Current shape:

| Column | Notes |
|---|---|
| `id` | PK |
| `profile_id` | FK → `profiles` — *whose* tracked keywords/niche this matched, not who authored it |
| `platform` | default `"x"` |
| `platform_post_id` | the external tweet's ID. Unique with `profile_id` — the same match won't be inserted twice for the same profile |
| `author_handle` | who actually posted it (a third party, not our profile) |
| `caption` | the content — this is what gets fed into `repurpose_caption` as `source_text` |
| `platform_url` | link to the original |
| `metrics` | JSON, optional — engagement snapshot at discovery time, if Xpoz returned one |
| `discovered_at` | when our poll found it, defaults to now |
| `alerted_at` / `alert_dismissed` | same alert-once pattern as `posts` |

Migration applied (`alembic/versions/46283ff46bfd_add_listening_matches_table.py`).

### Handoff — what exists, what's needed, what's not a blocker

**Exists already, nothing to wait on:**
- `listening_matches` table, migrated against the real DB (adjust the model and re-migrate as needed — see `CONTRIBUTING.md`'s "Database changes" workflow, same process as every other table).
- `repurpose_caption` already accepts raw `source_text` — feeding a match into a repurpose needs zero changes there, regardless of what `listening_matches`' final columns look like.
- `app/background/poller.py` already runs a tick loop per active `poll_config` row — the listening poll should extend this tick, not add a second loop.
- `XPOZ_API_KEY` is in `config.py`/`.env.example` already (optional field, won't break anyone's `.env` until it's required).

**Needs building (not done, no code to work around):**
- `app/services/xpoz.py` — an `XpozClient`, following the same shape as `PFMClient` (one `httpx.AsyncClient`, bearer auth, one method for now: fetch a user's recent tweets).
- Somewhere to store which handles a profile is listening to — not built yet, no fixed shape assumed. A JSON column on `poll_config` is one option; a separate table is another. Implementer's call.
- A tool (or the poller extension above) that calls `XpozClient`, applies the threshold check, and writes to `listening_matches`.
- A decision on how `GET /profiles/{id}/alerts/unread` surfaces these alongside (or separately from) `posts`-based alerts.

None of the "needs building" items block each other in a way that requires a specific order beyond: client → something calls it → results land in a table. Start wherever's easiest to verify first (e.g. the client against a real handle, before wiring up storage).

### Unconfirmed

Pricing, plan limits, and rate limits weren't checked (`/pricing`, `/api/plan`, `/api/usage` exist but weren't fetched) — check before relying on this for anything beyond light dev usage.

---

## Groq (primary LLM provider)

**Base URL:** `https://api.groq.com/openai/v1`

**Auth:** `GROQ_API_KEY` env var

**Client:** OpenAI Python SDK with `base_url` override

```python
from openai import OpenAI
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"],
)
```

**Models (verify live availability before building):**
- Large: `llama-3.3-70b-versatile` (voice extraction, hard repurpose, classification)
- Small: `llama-3.1-8b-instant` (easy repurpose)
- Groq also offers `openai/gpt-oss-20b` and `openai/gpt-oss-120b` with tool use — check which are on the free tier

**Free tier limits:** check current limits at build time. The free tier has request-per-minute and token-per-minute caps that change.

**Capabilities used:**
- Chat completions with tool calling (`tools` + `tool_choice` params)
- Structured JSON output (voice profile extraction)
- Standard chat completions (caption generation)

**When to use:** all text generation goes to Groq first. OpenRouter is the fallback. The must-keep judge runs on Jev (see below).

---

## Jev / TypeSafe AI (must-keep judge)

System One Model — structured decision outputs, not text generation. Returns typed values with calibrated probabilities in 70–500ms. Cannot hallucinate or produce type errors.

**API console:** `https://console.typesafe.ai/`

**Docs:** `https://docs.typesafe.ai/`

**Auth:** `TYPESAFE_API_KEY` env var

**Pricing:** $0.042/MTok input, output tokens are free.

**What it does in Lumi:**

The must-keep judge. Takes the original caption and the generated caption, returns a structured verdict:

```
Input: original caption + generated caption + must-keep items (URLs, @handles, numbers, dates)
Output: { intact: bool, confidence: float, missing_items: list[str] }
```

**Why Jev instead of the small Llama:**
- 70ms vs 2–5 seconds. The judge runs on every repurpose attempt, so this compounds.
- Calibrated confidence. If `confidence < threshold`, auto-retry instead of binary yes/no.
- No hallucination. The judge can't invent items that were "missing" or claim something survived when it didn't.
- Cheaper. Output tokens are free; the input is two short captions.

**Fallback:** if Jev is unavailable (early access, downtime), fall back to the small Llama on Groq as the judge. The spec already says "if the judge is unavailable, rely on the must-keep check and flag the caption for review." Jev being down triggers this path.

**Integration pattern:**

```python
# Jev call for the judge
result = typesafe_client.query(
    state={"original": original_caption, "generated": generated_caption, "must_keep": must_keep_items},
    questions={"intact": bool, "confidence": float, "missing_items": list}
)

if not result["intact"] or result["confidence"] < 0.8:
    # retry one tier up
```

Check the actual TypeSafe Python SDK for the correct call pattern. The above is pseudocode based on the docs.

---

## OpenRouter (fallback LLM provider)

**Base URL:** `https://openrouter.ai/api/v1`

**Auth:** `OPENROUTER_API_KEY` env var

**Client:** same OpenAI Python SDK, different `base_url`

```python
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)
```

**Models (verify live availability before building):**
- Primary free: `z-ai/glm-5.2:free` (strong tool calling, 1M context)
- Alternative free: `nvidia/nemotron-3-ultra-550b-a55b:free` (reasoning, 1M context)
- Use the `:free` suffix on model IDs for zero-cost inference

**Free tier notes:**
- Free models rotate with little notice. Do not hardcode a single model.
- Use OpenRouter's `models` array to list 2–3 free fallbacks in one request.
- Free endpoints may have stricter rate limits. Some free models have a known issue where tool calling fails with "No endpoints found that support tool use" — test before committing.
- Free model providers may train on your prompts. Acceptable for a hackathon demo.

**When to use:** only when Groq fails (429, timeout, model retired). The fallback is handled in Python:

```
try:
    response = groq_client.chat.completions.create(...)
except (RateLimitError, APITimeoutError, APIError):
    response = openrouter_client.chat.completions.create(...)
```

---

## Neatlogs (observability)

**Init:** call once at FastAPI startup and once at background task start.

```python
import neatlogs
neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], instrumentations=["openai"])
```

**Auth:** `NEATLOGS_API_KEY` env var

**What it traces automatically:**
- Every `chat.completions.create()` call via the OpenAI client
- Groq and OpenRouter calls (both use the OpenAI client)
- Inputs, outputs, tool calls, latency

**What needs manual spans:**
- Profile extract: `backfill_feed`, `validate`, `store`
- Listening: `poll`, `snapshot`, `velocity`, `alert`
- Caption repurpose: `route`, `enforce_limits`, `must_keep`, `judge`, `retry`, `user_action`

**Span budget:**
- Free plan caps at 100k spans/month
- Trace only runs that fire or fail for background polling
- A single repurpose with retry ≈ 10 spans
- Two eval runs of 20 captions ≈ 400 spans
- Budget the rest for demo usage and background polling alerts

**Tags required on every LLM call:**
- `routing_version`: identifies which routing rules produced this call
- `prompt_version`: identifies which prompt template was used
- These are needed for the before-and-after eval proof

**Init locations:**
- FastAPI `lifespan` startup event
- Background polling task start (verify in neatlogs docs whether the startup init propagates to asyncio tasks)

**Flush:** call at the end of short-lived tasks to ensure spans are sent.

---

## Entire (project record)

**Purpose:** holds the project's build record — checkpoints, graph output, building-in-public evidence.

**Status:** provider docs not yet reviewed. Do not build runtime dependencies on Entire until its API is understood.

**What it should hold:**
- Project checkpoints (code state at key milestones)
- Agent graph output (if Entire supports this)
- Build progress evidence for the "building in public" criterion (15% of score)

**What it should NOT hold:**
- Runtime data (that's the database)
- Traces (that's neatlogs)
- Business plan (that's cfo.ai)

**Action required:** read Entire's docs and update this section before building the integration.

---

## cfo.ai (business plan)

**Purpose:** document pricing, costs, revenue, and runway for the demo.

**Setup:**
1. Sign up at `cfo.ai/neathacks`
2. Cancel the subscription in Settings → Billing immediately after signup

**What to include:**
- Real costs: Groq free tier ($0), OpenRouter free tier ($0), Post for Me (check pricing)
- Projected costs at scale: what happens when the free tiers run out
- Revenue model: subscription tiers, per-user pricing
- Runway: how long the free tiers last at demo usage levels

**This is a document, not a code dependency.** Do not integrate cfo.ai into the application.

---

## Environment Variables Summary

| Variable | Service | Notes |
|---|---|---|
| `PFM_JWT_TOKEN` | Post for Me | JWT bearer token, app-level |
| `XPOZ_API_KEY` | Xpoz | Social listening, bearer access key — not yet added to `config.py`/`.env.example` |
| `GROQ_API_KEY` | Groq | Free tier |
| `TYPESAFE_API_KEY` | Jev / TypeSafe AI | Early access |
| `OPENROUTER_API_KEY` | OpenRouter | Free tier, no credit card needed |
| `NEATLOGS_API_KEY` | Neatlogs | Free plan, 100k spans/month |
| `DATABASE_URL` | PostgreSQL | Connection string |
| `SECRET_KEY` | FastAPI | Session signing |

---

## What actually shipped — implementation notes (2026-10-21)

The sections above are the pre-build contract; where reality diverged (verified against `app/agent/providers.py` + `app/agent/loop.py` today, the code wins):

**Groq models (§ "Groq / Post for Me" model list):** the spec'd `llama-3.3-70b-versatile` / `llama-3.1-8b-instant` were never adopted. The chain is `qwen/qwen3.8-27b` (primary; measured ~7,000-input-token request wall — a 413 above it) → `openai/gpt-oss-120b` (second candidate, ~8k wall, tool-calling verified). The small/large split the spec wanted exists as `TIER_MODELS` (`providers.py:22`): `small: openai/gpt-oss-20b`, `large: openai/gpt-oss-120b`, pinned per repurpose call via `model=` (same IDs on Groq and OpenRouter, so a tier applies to whichever provider answers). Above both sits the optional OpenLux provider (`OPENLUX_API_KEY` + `OPENLUX_MODEL`, prepended only when set).

**Fallback (§ "OpenRouter" — "The fallback is handled in Python"):** implemented as a nested chain, not the try/except pseudo-code below that line — for each provider in order (OpenLux → Groq → OpenRouter), try each of its `models` in order on any `openai.APIError`; a qwen 413/429 falls to `gpt-oss-120b` **before** the OpenRouter leg is touched; all candidates exhausted → `RuntimeError("all LLM providers failed")`. The "don't hardcode a single model / use the `models` array" advice was realized at the chain level rather than per-request, and request size is additionally bounded by the request-fit trim (`MAX_REQUEST_TOKENS = 6_700` estimated whole-request tokens incl. tool specs, `app/agent/loop.py`). Both landed 2026-10-21, pinned by `tests/test_provider_fallback.py` + `tests/test_context_budget.py`.

**Environment Variables Summary (table above):** stale rows — `XPOZ_API_KEY` *is* in `config.py`/`.env.example` now (optional); missing `OPENLUX_API_KEY`/`OPENLUX_MODEL` (optional), `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` (optional MCP connectors), and the `MCP_*` switches. See `AGENTS.md` §2 for the current table (env var **names** only — values never enter this repo).