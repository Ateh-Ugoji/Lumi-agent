# Database Model

## Scope

MVP targets **X (Twitter) only**. All three demo profiles are X accounts. The schema uses a `platform` column for future extensibility, but all seed data and all repurpose output targets X.

## Stack

- PostgreSQL
- SQLModel (SQLAlchemy 2.0 under the hood)
- Alembic for migrations

## Tables

### profiles

Seeded with 3 demo accounts. No auth — a profile switcher selects the active profile.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| name | String | Not null |
| platform | String | Not null. MVP: always `x`. Column kept for extensibility. |
| handle | String | Not null |
| pfm_account_id | String | Unique, not null |
| created_at | DateTime | Default now |

### posts

Backfilled from Post for Me. `alerted_at` enforces alert-once via conditional update:
`UPDATE posts SET alerted_at = now() WHERE id = ? AND alerted_at IS NULL`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null |
| platform_post_id | String | Not null |
| caption | Text | Not null |
| published_at | DateTime | Not null |
| alerted_at | DateTime | Nullable. Set once when a spike is detected |
| alert_dismissed | Boolean | Default false. Frontend filters unread alerts |

- Unique index on (`profile_id`, `platform_post_id`)

### metric_snapshots

Append-only. Post for Me returns lifetime totals, so velocity is computed from deltas between rows.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| post_id | Integer | FK → posts, not null |
| captured_at | DateTime | Not null |
| likes | Integer | Default 0 |
| comments | Integer | Default 0 |
| shares | Integer | Default 0 |
| views | Integer | Default 0 |

- Unique index on (`post_id`, `captured_at`)
- Index on (`post_id`, `captured_at DESC`) for velocity queries

### listening_matches

Social listening results from Xpoz. **Not the profile's own content** — `profile_id` here means "whose tracked keywords/niche this matched," not "who authored it." Added after `posts`/`metric_snapshots` were already settled as PFM-only/own-content; kept as a separate table for exactly that reason. See `external-services.md`'s Xpoz section for the full rationale and integration status.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null |
| platform | String | Not null. MVP: always `x`. |
| platform_post_id | String | Not null |
| author_handle | String | Not null — the third party who actually posted it |
| author_avatar_url | String | Nullable — author's picture URL from the handle DB (Chroma); null → the UI falls back to unavatar |
| caption | Text | Not null. Fed into `repurpose_caption` as `source_text` |
| platform_url | String | Not null |
| metrics | JSON | Nullable. Engagement snapshot at discovery time, if Xpoz returned one |
| discovered_at | DateTime | Default now |
| alerted_at | DateTime | Nullable. Same alert-once pattern as `posts.alerted_at` |
| alert_dismissed | Boolean | Default false |

- Unique index on (`profile_id`, `platform_post_id`)

### voice_profiles

One current profile per user. Voice examples stored as a JSON array to avoid a join table.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null |
| version | Integer | Not null |
| is_current | Boolean | Default false |
| payload | JSON | tone, emoji use, hook style, vocabulary, structure, things they never do |
| example_post_ids | JSON | Array of post IDs, 5–10 |
| created_at | DateTime | Default now |

- Unique index on (`profile_id`, `version`)
- Partial unique index on `profile_id` where `is_current = true`
- `example_post_ids` has no FK enforcement. Examples are a snapshot — posts are never deleted.

### style_answers

Fallback when post history is thin. 3–5 style questions.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null |
| question_key | String | Not null |
| answer | Text | Not null |
| created_at | DateTime | Default now |

### repurpose_requests

One per caption submitted for repurposing. `route_label` may be set by the agent (classify_difficulty tool) or by Python rules as fallback.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null |
| source_caption | Text | Not null |
| route_label | String | easy, standard, hard |
| created_at | DateTime | Default now |

### repurpose_attempts

One row per generation attempt. Holds retry and fallback history for the eval proof.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| request_id | Integer | FK → repurpose_requests, not null |
| platform | String | Target platform. MVP: always `x` |
| tier | String | small, large |
| model | String | Actual model ID used |
| provider | String | groq, openrouter |
| attempt_no | Integer | Not null |
| output | Text | Generated caption |
| must_keep_passed | Boolean | |
| judge_verdict | String | Nullable. yes, no, or null if judge unavailable. Source is Jev (with confidence), falls back to small Llama. |
| judge_confidence | Float | Nullable. Jev's calibrated confidence score. Null if Llama fallback was used. |
| created_at | DateTime | Default now |

### user_actions

Append-only. Logs every accept, edit, and reject.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| attempt_id | Integer | FK → repurpose_attempts, not null |
| action | String | accept, edit, reject |
| edited_text | Text | Nullable. Only set on edit |
| created_at | DateTime | Default now |

### poll_config

Controls background polling per profile.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, unique, not null |
| interval_minutes | Integer | Default 5 |
| is_active | Boolean | Default false |
| last_polled_at | DateTime | Nullable |

### chat_messages

Conversation history for the agent loop.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null |
| role | String | user, assistant, tool |
| content | Text | |
| tool_calls | JSON | Nullable. Tool call array from the LLM response |
| tool_name | String | Nullable. Which tool was called (for role=tool) |
| created_at | DateTime | Default now |

### user_search_requests

Handles the user explicitly asked Lumi to look up (pasted @usernames). Deliberately separate from the peer set (`peer_frameworks` / `listening_matches`): a user-requested recon never pollutes "my peers". Append-only; `already_requested` is computed at read time. Migration `d3c4b5a6978e`.

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK |
| profile_id | Integer | FK → profiles, not null, indexed |
| handle | String | not null. Normalized: no leading @, lowercase; validated `^[A-Za-z0-9_]{1,15}$` |
| request_note | String | Nullable. The user's ask, in their words |
| created_at | DateTime | Default now |

Written by the `save_user_request` tool only; it also reports peer-set membership and never writes the peer stores. Searching a saved handle is the separate `check_niche_trends` step (credit-burning); recording costs 0 credits.

## Notes

- No auth tables. Three profiles are seeded at startup.
- Post for Me JWT token is an environment variable (`PFM_JWT_TOKEN`), not stored in the database. Auth is bearer JWT, not a simple API key.
- Neatlogs holds all traces. No eval table needed.
- `example_post_ids` on `voice_profiles` is a JSON array. If posts were ever deleted, stale IDs would remain. Acceptable for a demo since posts are never deleted.
- `route_label` on `repurpose_requests` is set once. If the agent reclassifies on retry, the per-attempt tier column captures that.