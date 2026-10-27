# Background

`app/background/poller.py` — one asyncio task, started in `main.py`'s `lifespan` and cancelled on shutdown. Also `app/background/bootstrap.py` — per-profile voice + peer-framework bootstrap (scheduled from the OAuth callback and retried by the poller).

## Bootstrap pass (voice profile + peer frameworks)

Every poller tick (and immediately after a successful OAuth callback via `schedule_profile_bootstrap`), the poller runs `_bootstrap_pass()`: for **every** profile, call `bootstrap_profile(profile_id)`.

- **Voice profile**: if the profile has no `is_current` voice profile, run `extract_voice_profile` (which itself backfills from PFM if local posts are thin). If there still aren't ≥5 posts, it's a no-op and will retry next cooldown window.
- **Peer frameworks**: once a current voice profile exists and no `peer_frameworks` row exists yet (or the newest row is older than `FRAMEWORK_REFRESH_DAYS = 7`), run `check_niche_trends` (default handles), then the baseline-relative peer pipeline over those handles (`app/services/peer_pipeline.py`: per-account fetch → 28-day baseline → 1.5×-own-median winners → blind tagging → lift → synthesis). The report is persisted to `niche_framework_reports`/`post_taggings` and bridged into `peer_frameworks` + Chroma. No impression filter and no canned fallback any more — an unsupported run stores an honest `insufficient_data`/`failed` report with zero frameworks.
- **Cooldown**: each profile retries at most once every `BOOTSTRAP_RETRY_SECONDS = 300` (~5 min). Combined with the 120s tick, a thin profile gets another shot every other tick.
- **Never raises**: `bootstrap_profile` catches everything, logs a warning, and returns `{"error": ...}` — a failed bootstrap can't kill the poller.
- The poller itself is also exception-shielded per tick and per trending check, so one bad profile no longer silently kills background processing for the process lifetime.

## The full flow (backfill → metrics → spike → alert)

1. **Backfill** — each tick, before checking for spikes, the poller calls `backfill_profile_posts` for the profile, writing any new `Post` rows and inserting a **new** `MetricSnapshot` row per post. "Identify metrics" isn't a separate step from this — the metrics are part of what the feed call returns. If the backfill fails (bad account id, PFM down), it's logged and the spike check still runs on whatever data exists.
2. **Detect spike** — `check_trending` loads a profile's posts + each one's snapshot history, computes likes/hour between the two most recent snapshots, and compares it to that post's own earlier rate (`services.md` has the exact math).
3. **After a spike is detected — this is it, nothing else happens automatically:** `check_trending` sets `Post.alerted_at = now()` and `alert_dismissed = False`. No notification, no push, no event. It's a flag flip in the database.
4. The *only* consumer of that flag is `GET /profiles/{id}/alerts/unread`, which the frontend polls every 5–10s to surface a toast. From there it's on the user — via chat, `repurpose_caption` the post while it's hot (which auto-dismisses the alert), or `dismiss_alert` to clear it without acting.

**What "alerted" is for:** it's the trigger for "the user's own post is doing well right now, worth capitalizing on" — distinct from Xpoz/niche listening, which is "someone else's post is doing well, worth reacting to." Xpoz listening (`check_niche_trends`) is also triggered by the bootstrap pass and by the agent calling it directly.

## The poller loop itself

- **One shared loop, not one task per profile.** Every `TICK_SECONDS` it queries all `poll_config` rows with `is_active = true`, filters to the ones actually due (`last_polled_at` is null, or `interval_minutes` has elapsed), and runs backfill → `check_trending` for each. Then it runs the bootstrap pass.
- **`TICK_SECONDS = 120`.** This is just "how often do we check who's due," not "how often do we poll everyone" — that's `interval_minutes` (default 5), a separate per-profile knob. 120s keeps this from being needlessly chatty against the DB in normal operation.
- **For demos, drop `TICK_SECONDS` back to 30 (and consider a short `interval_minutes` too)** so a spike shows up on screen within a reasonable wait instead of up to 2 minutes later. Don't leave a demo-tuned value in as the real default. Keep PFM's rate limits (40 req/min) in mind: every due profile costs at least one feed request per tick.
- Shutdown is cooperative: `main.py` passes in an `asyncio.Event`; the loop waits on it with a timeout each tick (`asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)`), so it responds to shutdown within one tick instead of blocking a plain `sleep`.
- This calls the same `check_trending` tool function the agent can call directly — there's no separate "background version" of the spike-detection logic.
