# Services

`app/services/` — logic shared across tools (and usable by routers too), kept independent of the tool-calling framing.

## `pfm.py` — Post for Me client + backfill

Thin `httpx` wrapper, confirmed against PFM's real OpenAPI spec (`.agents/external-services.md` has the full picture). Three methods:

- `create_auth_url(platform, external_id, permissions)` — starts the OAuth connect flow, returns a URL to redirect the user to. Used by the `connect_account` tool.
- `get_social_account(account_id)` — account details (username, display name, status) by PFM's id.
- `get_account_feed(social_account_id, limit, cursor)` — cursor-paginated post history for a connected account. **Returns both `caption` and `metrics` per post in one call** — there's no separate metrics endpoint.

`backfill_profile_posts(session, profile_id, pfm_account_id)` is the one function that turns that feed into rows:

- Pages through the whole feed, skipping retweets (`RT @`) and replies (`@...`) — `posts` is meant to be the profile's own voice.
- **Dedup is by `(profile_id, platform_post_id)`**: an existing post is never re-inserted, but it always gets a **new** `MetricSnapshot`. That's deliberate — velocity needs a fresh data point every run.
- A 429 from PFM stops the run quietly (logged); the next poller tick picks it up. Any other HTTP error raises.
- Returns `{profile_id, new_posts, updated_posts}`. Traced in neatlogs as a `TOOL` span.

Called from three places: the `backfill_posts` tool, `extract_voice_profile` (when a profile has fewer than 5 posts), and the poller before each spike check.

## `metrics.py` — velocity math

Spike detection is based on **likes/hour**, computed from `MetricSnapshot` rows (append-only, so velocity is always a delta between two points, never a stored value):

- `current_and_baseline_velocity(snapshots)` returns `(current, baseline)`. `current` is the rate between the two most recent snapshots; `baseline` is the rate between the pair *before* that — i.e., "how fast was it growing right before the window we're calling a spike." Returns `(0.0, 0.0)` with fewer than 2 snapshots, and `baseline = 0.0` with fewer than 3.
- `detect_spike(snapshots)` is **relative to the post's own baseline**: it spikes when `current >= 3 × baseline` (`SPIKE_MULTIPLIER`). Below `SPIKE_FLOOR_LIKES_PER_HOUR = 5` it never spikes, so a post going from 0.1 to 0.4 likes/hour doesn't count. With no baseline yet (fewer than 3 snapshots), clearing the floor alone is enough.

Because the poller backfills before every check, a post needs about three ticks of history before relative detection kicks in.

## `enforcement.py` — the repurpose gate

Two independent stages, run in order, with an early exit:

1. **Deterministic checks** (`check_length`, `check_must_keep`) — pure Python, no API call. If either fails, `enforce()` returns immediately with `must_keep_passed=False` and **skips the judge entirely** (no point spending an API call on a draft that already failed).
2. **Judge** (`judge_caption`) — only runs if stage 1 passed. Degrades in three tiers:
   - **Jev** — a single `Noul` (yes/no with confidence) question via `typesafe-sdk`'s `system_one`; `noul >= 0.5` maps to `"yes"`.
   - **Small model on Groq** (`TIER_MODELS["small"]`, `gpt-oss-20b`) — if Jev raises `TypeSafeError`. Same question, JSON answer.
   - **No judge** — if both fail, the result keeps the deterministic pass but sets `judge_verdict=None` and feedback "flagged for manual review".

`EnforcementResult.judge_source` is `"jev"`, `"llm_fallback"`, or `"none"`. Both judge paths are `GUARDRAIL` spans in neatlogs. Known wart: the fallback builds its own OpenAI client instead of going through `providers.py` — see `CONTRIBUTING.md`'s Tasks.

## `repurpose.py` — difficulty routing + rewrite

- `classify_difficulty(source_text, platform, must_keep_phrases)` labels a request `easy`/`standard`/`hard`. **Jev first** (a `Choice` question, given the caption length, platform limit, and must-keep phrases), and `classify_difficulty_by_rule` if Jev errors. The rule: over 280 chars for X, or 3+ protected items (must-keep phrases + URLs + @handles) → hard; X with nothing to protect → easy; everything else (including every non-X platform) → standard.
- `ROUTE_TIERS` maps the label to a model tier: easy → `small`, standard/hard → `large`. Model IDs live in `TIER_MODELS` in `app/agent/providers.py`.
- `generate_platform_repurpose(..., tier)` rewrites using platform-specific rules (X, LinkedIn, TikTok, Instagram) plus the current voice profile. Besides the rewrite it returns `tier`, `model`, and `provider` for the attempt row. If the LLM call or JSON parse fails, it returns the source text unchanged rather than raising.

## Others

- `voice.py` — `extract_voice_from_captions(captions)`, the LLM call behind `extract_voice_profile`.
- `xpoz.py` — `XpozClient`: `get_user_live_posts(username)` (a public account's recent tweets) and `search_live_posts(query)` (keyword search). Third-party content only — never written to `posts`.
- `peer_pipeline.py` — `run_peer_pipeline(...)`, the orchestrator behind `discover_and_extract_niche_frameworks` and bootstrap `_ensure_peer_frameworks`: fetch → baseline → blind `tag_posts` (in `app/analysis/extract.py`) → lift → synthesis → persistence (`peer_store.py`), plus `legacy_payload_from_report`/`winner_post_dicts` for the `peer_frameworks`/Chroma bridge. (`frameworks.py` — the old one-shot `extract_peer_frameworks` with its canned fallback — was deleted 2026-10-26.)
