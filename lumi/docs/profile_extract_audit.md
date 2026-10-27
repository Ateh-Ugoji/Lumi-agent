# Profile Extract — Step 0 Audit (read-only, real data)

Run 2026-10-17 against `lumi.db` (SQLite, 2 profiles, 39 posts, 39 metric_snapshots,
9 user_activity rows) plus live read-only probes of PFM and Xpoz.
Each finding reports the number first, then example IDs. Nothing was guessed;
"not measurable" means the DB/code has no field for it.

## 1. Metrics: missing-as-zero in `metric_snapshots`

- **39 snapshots total; `views == 0`: 24 (61.5%).** Example IDs: snapshot 21 (post 21),
  22 (post 22), 23 (post 23).
- **`views == 0 AND (likes|comments|shares > 0)`: 0 (0.0%).** The pattern named in the
  brief is absent.
- **All four metrics `== 0`: 24 (61.5%)** — the stronger form of the same poison:
  an entire metrics payload was missing at insert and got coerced to four zeros.
  **All 24 belong to profile 16 (`just_ateh`); all 15 profile 2 snapshots have `views > 0`.**
  Examples: snapshot 21 (post 21, captured 7,150.5 h after publish), 22 (11,316.5 h), 23 (15,253.3 h).
- Migration impact: the brief's Rule A (`views==0` with any other metric >0 → NULL)
  matches **0 rows today**. Rule B (all four zero **and** snapshot taken >72 h after
  publish) matches **24 rows** — a zero-view post older than 3 days is a payload loss,
  not performance. Rule B is applied with a comment; see Step 1.

## 2. Snapshot ages (`captured_at − published_at`, hours)

- n=39: **min 3.27 h, p25 48.8 h, median 16,389.5 h (~683 days), p75 21,801.6 h, max 24,927.0 h (~1,038 days).**
- Distribution: **<6 h: 1 · 6–72 h: 10 · >72 h: 28 (71.8%).**
- **Zero snapshots near the 24 h / 72 h / 7 d / 30 d targets** — ages reflect ingestion
  time, not post maturity.
- **Every post has exactly 1 snapshot (max across posts = 1)** — no refresh pass has
  ever run; spike detection (`detect_spike` needs ≥2) is dead, confirming the deep map.
- Per profile: profile 16 snapshots were taken 7,150–24,927 h after publish (posts
  published 2023-12-08 → 2025-12-18); profile 2's posts were published 2026-10-08 → 2026-10-12.

## 3. Threads / self-replies

- `user_activity` columns: `id, profile_id, platform, platform_post_id, kind, caption,
  published_at, created_at` — **no parent/conversation fields → "parent author is the
  user" is NOT measurable** from stored data.
- Text-shape proxy (caption starts with the user's own handle): **profile 2 = 0 of 9
  replies; profile 16 = 0** (it has no activity rows at all).
- Verdict: suspicion neither confirmed nor killable structurally today. Live Xpoz probes
  (§Capabilities) show `replyToTweetId/replyToUserId/replyToUsername` exist, so post-change
  ingestion can detect self-replies exactly instead of guessing.

## 4. Truncation

- Posts with 270 ≤ len ≤ 280 **and** ending in a link/ellipsis: **0**.
- Posts with len 275–280 at all: **0** (no boundary cluster to inspect).
- **Posts longer than 280: 7** — examples post 48 (715 chars), 45 (546), 7 (509);
  full set: 287, 298, 303, 304, 509, 546, 715 chars. Long-form arrives whole.
- Verdict: truncation suspicion **not supported** for current paths. Detection guard is
  still implemented (flag + exclude from hook/body analysis) because no API guarantees
  `text` is complete, and there is currently **no fetch-full-text endpoint** documented
  (`docs/xpoz_capabilities.md` does not exist yet — niche Prompt 1 Step 0 owns it).

## 5. Originals per profile (depth)

- Profile 2 `@AtehOfficial`: **15 originals — below 20** (thin history for niche extraction).
- Profile 16 `@just_ateh`: **24 originals.**
- **Which ingestion path produced them: NOT measurable** — `posts` has no `source`
  column (added by this change: `pfm` | `xpoz`).

## 6. Feed coverage per ingestion path

- **Per-path attribution: NOT measurable** (no `source` on `posts` or `user_activity`).
- Totals: profile 2 = **9 replies, 0 retweets**; profile 16 = **0 activity rows**.
  **Retweets observed across the whole DB: 0** (ever).
- **PFM live probe: `get_account_feed` → HTTP 401 Unauthorized** at audit time (it was
  returning 500 earlier the same day) — the feed cannot be probed live at all right now.
  Historical evidence: the 9 replies came from PFM-fed captions, so PFM *does* return
  reply-shaped items; whether it ever returns retweets is **unconfirmed** (0 observed —
  could be API or user behaviour).
- Xpoz own-handle live fetch: `AtehOfficial` → 20 posts, `sama` → 20, **`just_ateh` → 0**
  (no data served for that handle).

## 7. Duplicates and drift

- Duplicate `(profile_id, platform_post_id)` rows: **posts 0, user_activity 0**; same ID
  present in both tables: **0**.
- **Posts with >1 snapshot: 0 → cross-pass value drift is NOT measurable** (there has
  been only one pass ever, §2).
- **Metric-field-name drift: NOT measurable in the DB** (every path normalizes into fixed
  columns before insert). Code-level drift confirmed by reading: PFM paths read
  `like_count|likes`, Xpoz reads `likeCount` — two different mappings that can disagree.
  This change unifies all three paths behind one normalizer (`app/services/ingest.py`).

## Capabilities (live read-only probes, 2026-10-17)

These were unverified assumptions; now measured:

- **Xpoz user-live allowed `fields`** (from the endpoint's own 400 body): `id, authorId,
  authorUsername, text, bookmarkCount, impressionCount, likeCount, lang, possiblySensitive,
  deleted, suspended, quoteCount, replyCount, retweetCount, isRetweet, hasBirdwatchNotes,
  birdwatchNotesId, birdwatchNotesText, birdwatchNotesUrl, status, conversationId,
  quotedTweetId, retweetedTweetId, replyToTweetId, replyToUserId, replyToUsername,
  originalTweetId, editedTweets, hashtags, mentions, mediaUrls, urls,
  grokGeneratedContent, sourc…` (truncated by the API message itself).
- Accepted individually: `quoteCount`, `bookmarkCount`, `isRetweet`, `conversationId`,
  `lang`, `authorId`. **Rejected: `isReply`, `isQuote`, `mediaType`** — use
  `replyToTweetId` / `quotedTweetId` instead.
- **Pagination works**: `limit` is ignored (always **20 results/page**); envelope =
  `{count, dataSource, has_more, next_page_cursor, results}`; **`cursor=<next_page_cursor>`
  verified** (page 2 first-id ≠ page 1). `offset`/`page`/`next` are ignored; a non-token
  `cursor` value → 500. ⇒ depth backfill to 100 originals = 5 pages.
- Xpoz search endpoint (`/posts/live`): intermittent 400 field-validation / 401
  Unauthorized — flaky, treated as unavailable for this change.
- PFM feed: 401 (see §6).

## Consequences for the fix (decisions made from these numbers)

1. Rule A (brief) + **Rule B (audit-driven)** migrate 24 rows; zeros ≤72 h stay untouched
   (a genuinely new post can be at zero).
2. Snapshot policy targets 24 h/72 h/7 d/30 d milestones — nothing in the DB does this today.
3. Deletion detection and per-path provenance are built from scratch (§5, §7).
4. Xpoz is the only *provable* ingestion source right now (PFM 401); its cursor
   pagination unlocks the 100-original depth target.
5. Full-text fetch for truncated posts: **not implemented** — no endpoint exists yet;
   flagged posts stay flagged and are excluded from analysis (§4).
