# Blueprint fix — what still has to be built (B) and what still has to be documented (C)

Tracker written 2026-10-26 after the full `AGENTS.md` review. Three buckets were identified; **bucket A (sync `AGENTS.md` + the flow map to the code) is already done** — see the bottom of this file. This file holds the other two.

Ground truth re-run on 2026-10-26 (after the peer-pipeline Prompt 3 wiring):

| Check | Result |
|---|---|
| `uv run ruff check .` | ✅ all checks passed |
| `uv run pytest -q` | ✅ 422 passed (40 test files) |
| `uv run alembic current` | ✅ `cefd455456a2 (head)`, 21 tables |
| `uv run alembic check` | ✅ passes (B-1 fixed 2026-10-26; it failed at review time) |
| `grep -rn "Milestones & Shipped Tech" app/ tests/` | ✅ no matches (canned fallback deleted, Prompt 3) |
| Registered tools | 20 `@tool(` decorators (matches `AGENTS.md`) |
| Routers / routes | 9 routers / 23 routes |
| Git | branch `main`, 63 dirty files (43 modified + 20 untracked) |

Priority key: **P0** = blocks or endangers everything else · **P1** = the main remaining feature work · **P2** = correctness/quality debt in what already ships · **P3** = external unblocks and product decisions.

---

## Bucket B — the blueprint is ahead of the code

### P0 — foundations (do these first)

**B-1. Make `alembic check` pass before any new migration. — ✅ done 2026-10-26** (`legacy/alembic/env.py` gained an `include_object` hook that skips the one known expression index, and only when the URL is SQLite; `alembic check` now exits 0).
Autogenerate reads the SQLite expression index `ix_metric_snapshots_post_id_captured_at_desc` (`metric_snapshots`, `sa.literal_column('captured_at DESC')`) as a *changed* plain index and proposes `remove_index` + `add_index`. The consequence is real: the next `alembic revision --autogenerate` (and the peer/niche work in B-4/B-5 needs migrations) would silently drop a DESC index and recreate it without the expression.
Fix options: teach `legacy/alembic/env.py` to skip that index in comparison, or declare it in a dialect-agnostic way that SQLite can round-trip.
*Verify:* `uv run alembic check` exits 0; `uv run alembic revision --autogenerate -m test` emits no ops for `metric_snapshots`, then discard that file.

**B-2. Fix the SQLite voice-profile partial unique index. — ✅ done 2026-10-26** (the model's `sqlite_where` had already landed; added migration `2f30380b96df` to rebuild the index on existing SQLite databases with a documented one-way downgrade, plus 3 tests in `legacy/tests/test_voice_index_sqlite.py`).
`uq_voice_profiles_current_per_profile` is declared only with `postgresql_where` (`legacy/app/models/voice.py`, migration `2fe84cc3dec6:103`); SQLite ignores it, so the shipped `lumi.db` has a **plain UNIQUE on `profile_id`** — a second voice-profile version fails with `IntegrityError` even when flip-before-insert+flush is correct. Versioned voice profiles are therefore broken on the local dev DB and only work on Postgres.
Fix: dual-dialect `sqlite_where=sa.text("is_current = 1")` or a CHECK-based design, plus a migration.
*Verify:* a test that inserts v1 (current), flips it, and inserts v2 (current) on a **fresh SQLite** DB; `alembic upgrade head && downgrade -1 && upgrade head` round-trip.

**B-3. Land the 63-file dirty working tree as reviewable commits.**
43 modified + 20 untracked files, including whole features (`legacy/app/agent/turn_class.py`, `legacy/app/routers/repurpose.py`, `legacy/app/services/repurpose_flow.py`, `legacy/app/services/turn_metrics.py`, `legacy/app/background/mcp_refresh.py`, `legacy/alembic/versions/f3a7c9e2b41d_*`, `legacy/tests/test_turn_class.py`, `legacy/tests/test_coverage_gate.py`, `legacy/tests/test_repurpose_endpoint.py`, `legacy/scripts/classifier_report.py`, frontend `WorkingMark`/`formatClock`, plus junk: `_purge_p16.py`, `temp-agents.md`). Building further on top of an unreviewable tree is how the docs got out of sync in the first place.
Suggested split: (1) turn classification + `turn_classifications` migration + health latency, (2) evidence gates (claim/coverage/finish_reason), (3) `POST /repurpose` + `repurpose_flow`, (4) MCP background refresh, (5) handle-search platform selector + Chroma quota hardening, (6) frontend AgentThinking/WorkingMark, (7) delete `_purge_p16.py` / decide on `temp-agents.md`.
*Verify:* `git status --short` empty (or only deliberately-untracked files), `uv run ruff check . && uv run pytest -q` still green after each commit.

### P1 — the two staged pipelines (the actual remaining features)

**B-4. Peer-framework pipeline — `opencode_prompts.md` Prompts 1–3. — ✅ done 2026-10-26**

> Note: the plan source `opencode_prompts.md` is **not in the repo** (it lives at `C:\Users\USER\Downloads\opencode_prompts.md`); it was followed from the in-repo contract instead: `legacy/app/schemas/peer.py` + the AGENTS.md staged section.
>
> **All three prompts landed on 2026-10-26:**
> - **Prompt 1 (deterministic + LLM tiers):** `legacy/app/analysis/winners.py` (`ScrapedPost`, shared 28-day baseline, blind `select_winners` — per-account `outlier ≥ 1.5×` own median, the *only* bar after `MIN_VIEWS_FLOOR=500` was removed; pinned/reply/repost/boosted/<24h excluded, ≤5/account, top 20, <8 ⇒ `insufficient_data`), `legacy/app/analysis/extract.py` (blind tagging: ids + text only, batched, honest `failed` rows, 13 tests), `legacy/app/analysis/synthesize.py` (lift-grounded frameworks/pillars/whitespace, `insufficient_data`/`failed` reports carry no frameworks, 8 tests). Decisions applied: baseline window 90 → **28 days** (shared with your own posts), under-24h excluded everywhere, no fixed views floor. Tests: `test_peer_winners.py` (12) + `test_peer_extract.py`/`test_peer_synthesize.py`.
> - **Prompt 2 (persistence):** migration `cefd455456a2` adds `niche_framework_reports` (one JSON `NicheFrameworkReport` per row) + `post_taggings` (unique `(post_id, prompt_version)`), written via `legacy/app/services/peer_store.py` (save/upsert/`latest_report`/`cached_taggings` — failures never replayed). Tests: `test_peer_store.py` (7).
> - **Prompt 3 (wiring + fallback deletion):** `legacy/app/services/peer_pipeline.py` orchestrates fetch → baseline → winners → blind tagging (cached) → lift → synthesis → persistence; both live entry points call it (`discover_and_extract_niche_frameworks` and bootstrap `_ensure_peer_frameworks`); `legacy/app/services/frameworks.py` — with the canned "Milestones & Shipped Tech" fallback — is **deleted**. `min_impressions` is gone from the tool schema. Bridge: `legacy_payload_from_report` keeps `peer_frameworks`/Chroma fed with report-derived content only. Tests: `test_peer_pipeline_wiring.py` (2) + reworked `test_xpoz_resilience.py`/`test_handle_db.py`.
>
> **Still blocked on external:** Xpoz `fields` verification (so `docs/xpoz_capabilities.md` can exist and pinned-post detection become real) and the per-run credit estimate for the ≤8-account × 60-posts scan.

**B-5. Niche extraction pipeline — `niche_opencode_prompts.md` Prompts 1–3.**
Schemas landed (`legacy/app/schemas/niche.py`, 11 tests); the niche is still `DEFAULT_NICHE_QUERY` / `DEFAULT_NICHE_HANDLES` constants with no location data, no reply parents, no comments.
1. *Step 0 (blocking)* — write `docs/xpoz_capabilities.md`: profile lookup, structural post flags (`is_reply`/`is_quote`/`conversation_id`), parent-post fetch, comment fetch + commenter fields, bookmark/quote counts, search query syntax. **Do not build ingestion on unverified Xpoz assumptions.** Report credit cost per user alongside it.
2. *Prompt 1* — additive nullable columns on `profiles`/`posts`/`metric_snapshots`/`user_activity` + new tables `post_comments`, `profile_niche`, `niche_keywords`, `niche_registry`, `niche_peers` (`niche_key = topic_slug:geo_scope` — geo must be in the key or Nigerian and US fintech share one benchmark pool).
3. *Prompts 2–3* — `app/niche/{features,synthesize,postprocess,discover}.py`, then **delete** the hardcoded lists (`bootstrap.py:27-30`, `prompts.py:13-14`, `trends.py:32-34`, frontend) and point bootstrap/prompts/trends at `niche_peers`.
*Verify:* `uv run pytest -q` green; a grep for `DEFAULT_NICHE_QUERY`/`DEFAULT_NICHE_HANDLES` returns nothing after Prompt 3; thin-history runs return `status: thin_history` and **ask the user** rather than inventing a niche.**B-6. Own post tagging — peer Runtime Prompt A.** `own_post_analysis` rows are written with `status='pending'` and stay that way until the peer pipeline's tagging step exists. Depends on B-4 Prompt 1/2 — **that dependency was satisfied 2026-10-26** (B-4 complete), so this is now the ready-to-build next step.
*Verify:* after it lands, `uv run python legacy/scripts/own_report.py` shows no `pending` rows for analyzed posts.

### P2 — correctness debt in what already ships

**B-7. Provider exhaustion still 500s `POST /chat`.** `chat_completion_with_fallback` raises `RuntimeError("all LLM providers failed")`, which the loop does not catch — the user message is already persisted as a dangling row and the non-stream endpoint returns a bare 500 (the stream endpoint converts it to an `error` event). Catch it in the loop and return an honest `{error}` reply.
*Verify:* a test that mocks every provider failing and asserts a 200 with an honest message (or a documented, structured 502) — not a 500.

**B-8. Empty-content assistant rows leak into the UI.** Tool-calling turns with no prose persist `content=""`; `/chat/history` filters only `role != TOOL`, so the frontend renders empty bubbles. The model context drops them (`loop.py:462`) — DB, UI and model context disagree.
*Verify:* a test asserting `/chat/history` skips blank assistant rows (or that the loop never persists a blank one).

**B-9. Empty/whitespace user message** is persisted but filtered from context, so the model can receive a prompt with no user turn and history ending on an assistant message (some backends 400 that). Reject empty input at the router with a 422 instead.

**B-10. Poller hardening.** Per-tick and per-profile `try/except` now exist, but there is no backoff/alerting (failures are logged and retried every 120s forever), and `now - last_polled_at` still risks a naive/aware `TypeError` on SQLite.

**B-11. `legacy/app/seed.py` half-rewrite.** Docstring and log promise "purging all third-party accounts" / "Only user accounts retained" but **no delete code exists**; `USER_HANDLES`/`USER_PFM_IDS` are dead; the existing row's `name` is unconditionally clobbered to `"Ateh Ugoji"` on every boot. Either implement the purge or fix the wording, drop the dead constants, and stop overwriting user-supplied names.

**B-12. Turn classifier stage 2 is default OFF.** Rules-only classification currently decides every turn (`TURN_CLASS_JEV_ENABLED` off). Use the read-only `uv run python legacy/scripts/classifier_report.py` output (other-rate, Jev-vs-rule disagreement, misrouted rows) to decide whether to enable it and what the 0.85/0.6 thresholds should be. Related: `turn_classifications.credits_spent` and `user_corrected` stay NULL until something actually meters them — decide whether metering is in scope.

### P3 — external unblocks & product decisions

**B-13. External credentials:** renew `PFM_JWT_TOKEN` (every ingest path — backfill, analytics ingest, voice extraction — is parked on it), run the Google MCP GCP checklist (client id/secret → `/mcp/google/connect` is an honest 503 today), and decide the Xpoz credit budget (handle-search fan-out + B-4/B-5 scans).

**B-14. Auth / CORS.** `allow_origins=["*"]`, no `allow_credentials`, no auth layer at all: any origin can drive chat, profile select, history delete. Decide the posture before anything is exposed beyond the demo.

**B-15. Frontend product gaps.** `POST /profiles/{id}/select` is never called, so server chat history and the localStorage history diverge; unread-alerts polling is unimplemented (README still claims it polls every 5–10s); several dead components (`ThinkingState`, sim subsystem, `LoginScreen`/`OAuthCallback` theme aliases). Decide what the next milestone needs before cleaning.

---

## Bucket C — the docs are behind the code

`AGENTS.md` and the flow map are now synced (bucket A, below). Everything else still describes the hackathon-weekend state. Ordered by how misleading it is.

| # | File | Stale claim | Fix |
|---|---|---|---|
| C-1 | `.agents/api-endpoints.md` | `:5`, `:174`, `:357` — "multi-platform repurposing out of scope", "`platform` … always `x`" (false: `repurpose_flow` writes the real platform; `POST /repurpose` accepts 9 frontend ids). 9 routes undocumented: `POST /chat/stream`, `POST /chat/title`, `DELETE /chat/history`, `GET /profiles/{id}/analytics`, `POST /pfm/connect`, `GET /pfm/callback`, `GET /trends/matches`, `POST /trends/scan`, `GET /health`. `:34` example tool names (`classify_difficulty`, `generate_caption`, `check_must_keep`, `judge_intact`) don't exist. `:87` "list all seeded demo profiles" + a `"platform": "instagram"` example | Add the 9 routes (the spec is the contract CLAUDE.md points at), correct the scope lines, replace the fake tool names with real ones, fix the profile semantics |
| C-2 | `README.md` | `:43`/`:159` "3 demo profiles" / "Three seeded X accounts" (one real account); `:80` lists 11 native tools (there are 20 + MCP); `:86-92` endpoint table lists 5 (there are 23 across 9 routers); `:101` Xpoz "not yet integrated" | Update numbers, seed description and endpoint table |
| C-3 | `CLAUDE.md` | `:28` routers = `chat`/`profiles`/`alerts` (there are 9); `:33` "seeds 3 demo profiles (idempotent by handle)"; architecture blurb misses `voice`, `handles`, `mcp_google`, `repurpose` | Rewrite the architecture paragraph |
| C-4 | `CONTRIBUTING.md` | Task list is the de-facto roadmap and is out of date: task 1 (stub tools) done, task 4 (three demo profiles) obsolete, task 5 (backfill pipeline) done, "retry one tier up" done (`repurpose_flow`), task 11 (`route_label`) done; `:54` "3 test files / 15 tests" (now 34 / 373); `:118` commit style `<verb>: <what>` vs the repo's actual conventional commits | Mark tasks done/obsolete, refresh counts and commit-style note |
| C-5 | `docs/routers.md` | `:3` says "eight files" — there are nine; `legacy/app/routers/repurpose.py` has no section; per-route notes predate the `handles`/`mcp_google` sections in some places | Add `repurpose.py`, update the count |
| C-6 | `docs/tools.md` | `check_trending` "inert in practice until a metrics-refresh pass exists"; the `repurpose_caption` bullet still says 280-char enforce limit, "`route_label` is never set", "`platform` on the attempt row keeps its default"; no mention of the shared `repurpose_flow` / `POST /repurpose`; no `turn_class`-driven tool tiers | Rewrite the repurpose bullet, un-inert `check_trending`, add the tier/fast-path note |
| C-7 | `docs/services.md` | `backfill_profile_posts` "skips retweets and replies" — they are now classified and routed to `user_activity` by `legacy/app/services/ingest.py` | Update to the shared ingest policy |
| C-8 | `docs/background.md` | `:7` and `:26` still run `_bootstrap_pass()` "every poller tick" / "then it runs the bootstrap pass" — bootstrap was **removed** from the tick (it hangs long enough to fail the healthcheck) and runs on demand from the PFM OAuth callback | Fix the two passages (its backfill-per-tick text is already correct) |
| C-9 | `docs/frontend-integration.md` | `:23` "The five endpoints"; the status table is a frozen "verified just now" snapshot | Update the count; mark the status table as time-stamped |
| C-10 | `.agents/database.md` | `:114` `route_label` "set by the agent (classify_difficulty tool)" (now a service function, written for real); `:133-135` `tier/model/provider` (now written); `:17` "seeded with 3 demo accounts"; `:64` `listening_matches` "integration status" | Refresh the four entries |
| C-11 | `.agents/setup.md`, `.agents/external-services.md` | `create_all` listed in `database.py` (every other doc forbids it; it doesn't exist); `eval/captions.json` + `scripts/run_eval.py` planned but absent; `XPOZ_API_KEY` missing from the env list; `:196-197,275-281` recommend `llama-3.3-70b-versatile`/`:free` suffixes and "don't hardcode a single model" vs the hardcoded chain | Trim dead plans, align model guidance with `providers.py` |
| C-12 | `docs/agent.md` | Greeting-gate description predates turn classification (fast/full path, per-class tool tiers, `effort=low`); no mention of the 6,700-est-token request budget or the provider model chain | Rewrite the routing section |
| C-13 | Repo hygiene | `_purge_p16.py` (one-off purge script) and `temp-agents.md` are untracked in the project root; `frontend/` ships both `package-lock.json` and `pnpm-lock.yaml` | Delete or commit the one-offs; pick one package manager |

---

## Definition of done

- Every item names a command or grep that proves it.
- Any change to a pipeline, schema/table, tool, data flow or provider updates `AGENTS.md` + `docs/flow-map.md` + `docs/flow-map.html` **in the same change** (AGENTS.md §MANDATORY WORKING PROCESS item 6) — that rule is what this file exists to enforce.

## Bucket A — already done (2026-10-26)

`AGENTS.md` re-synced to the code (code wins): route inventory 22 → **23 routes / 9 routers** (added row 23 `POST /repurpose`), router/health line refs (`main.py:93-101`, `104-115`), **new §6b** for `legacy/app/services/repurpose_flow.py` + the REST endpoint, `repurpose_caption` tool paragraph rewritten (request now written *after* the pipeline, real `platform`/`tier`/`model`/`provider`, `platform_char_limit` instead of a hardcoded 280), **§7 poller rewritten** (per-profile + per-tick exception handling, metrics backfill, decay pass, bootstrap removed from the tick), §11 bug roundup item 5 flipped from "no error handling" to "fixed + open timezone risk", test counts 279/28 → **373/34**, git state `ateh` → **`main`**, contradiction bullets' endpoint/tool counts corrected, `route_label`/`tier`/`model`/`provider` claims flipped to "written", seed-purge claim corrected, migration count 5 → **8 revisions** with the `alembic check` failure recorded. `docs/flow-map.html`'s "the poller itself still never fetches new metrics" corrected; `docs/flow-map.md` was already current (verified against the code, no changes needed).
