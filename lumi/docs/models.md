# Models

`app/models/`, one file per table group. Schema is Alembic-managed — edit a model, then generate+apply a migration (see `CONTRIBUTING.md`). No `create_all()` anywhere.

## `voice_profiles` is versioned, not updated in place

`extract_voice_profile` never overwrites a voice profile — it inserts a new row with `version = max(version) + 1` and `is_current = True`, and a **partial unique index** (`is_current = true`, per `profile_id`) guarantees only one current row exists.

That means any code writing a new current version must flip the old one to `is_current = False` *and flush* before inserting the new row — `extract_voice_profile` does this:

```python
current.is_current = False
session.add(current)
await session.flush()          # old row's index entry must update before the new insert
# ... then insert the new VoiceProfile with is_current=True
```

Skip the flush (or do it in the wrong order) and the insert can violate the partial unique index. `get_voice_profile` only ever reads the current row — history lives in the table but isn't exposed through that tool.

The index is declared with **both** `postgresql_where` and `sqlite_where` (`is_current = 1`) — SQLite ignores dialect-scoped kwargs and would otherwise degrade the index to a plain `UNIQUE(profile_id)`, breaking versioning on the local dev DB (it did; the shipped `lumi.db` index was repaired in place).

## `posts` vs `user_activity` — originals vs everything else

One predicate, `classify_post_kind(caption)` (`services/pfm.py`), applied in all three ingestion paths (shared backfill, analytics PFM ingest, analytics Xpoz ingest):

- **original** (incl. quote tweets with own commentary) → `posts` — the only input for voice extraction, captions/repurpose, and analytics.
- **reply** (`@`-opener) → `user_activity` — the user's own words. Read by the `get_user_activity` tool (conversational depth: "since you said X…") and, as reply samples only, by voice extraction into the `reply_style` payload field.
- **retweet** (`RT`/`RT @`/`RT:` opener) → `user_activity` — content the user *shared*, never authored. Never attributed to the user, never voice material.

`user_activity` is unique on `(profile_id, platform_post_id)`; `upsert_user_activity` dedupes on insert. PFM/X expose no structural reply/RT flags (verified against their OpenAPI spec), so classification is text-heuristic; quotes are kept because the commentary is the creator's own words.

## `posts.alerted_at` / `alert_dismissed` is an alert-once pattern

`check_trending` sets `alerted_at` the first time a post's velocity crosses the spike threshold, and leaves it alone on subsequent checks **unless the alert was already dismissed**:

```python
if post.alerted_at is not None and not post.alert_dismissed:
    continue  # already alerted, user hasn't acted yet — don't re-alert
```

So a post can alert again after being dismissed, but never spams repeated alerts while one is still pending. `dismiss_alert` (a tool) just sets `alert_dismissed = True` — it doesn't touch `alerted_at`.

## `posts` vs `listening_matches` — don't conflate these

`posts` is the profile's **own** backfilled content (from Post for Me) and powers voice extraction only. `listening_matches` is content from **other people** that Xpoz surfaced as relevant to a profile's tracked keywords/niche — `profile_id` there means "whose listening config matched this," not "who posted it." It feeds `repurpose_caption` as a `source_text` candidate, never voice extraction. Same alert-once shape as `posts` (`alerted_at`/`alert_dismissed`), same unique-by-`(profile_id, platform_post_id)` constraint. Only the on-demand `check_niche_trends` tool writes to it so far, and nothing sets its `alerted_at` yet — see `CONTRIBUTING.md`'s Tasks list.

## Everything else

- `metric_snapshots` is append-only; unique on `(post_id, captured_at)` so you can't double-write the same snapshot. Velocity is always computed from deltas between rows, not stored directly — see `services.md`.
- `repurpose_attempts.must_keep_passed` (deterministic Python check) and `judge_verdict`/`judge_confidence` (Jev judge) are independent columns. The judge fields are `null` whenever the deterministic check already failed — the judge is skipped entirely in that case to save an API call. There is no LLM fallback when Jev itself is down (an outage raises).
- `repurpose_requests.route_label` and `repurpose_attempts.tier`/`model`/`provider` are **never written** by current code — always `null` (the attempt row keeps its model-level defaults).
- `chat_messages.tool_calls` (JSON) is only populated on assistant turns that requested tool calls — plain replies leave it `null`.
- `posts` is unique on `(profile_id, platform_post_id)`, not globally — the same external post ID can't collide across profiles unless it really is the same post for that profile.
