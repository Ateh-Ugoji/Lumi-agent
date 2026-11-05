# TEMP — Keys audit: Xpoz, Chroma, and everything else that is not fully working

Status: **audited live 2026-10-29**, remediation plan included. Branch `Ateh-branch`.
Evidence: `manage.py check_keys` (today), one live Xpoz call per key (today), the backend's
LLM traceback (today). No key value is ever printed here — only statuses.

---

## 1. The answers, point by point

### "How is the XPOZ API not enabled?"

Because `XPOZ_LIVE_ENABLED` is **absent from `lumi/.env`** → the client default is `false`
(`apps/connections/clients/xpoz.py:193` `live_enabled`). Nothing is broken: both keys load
(`check_keys`: *"2 key(s) cargadas, llamadas en vivo desactivadas, tope 12 créditos por corrida"*).
It is a deliberate spend-guard — the plan is 500 one-time credits, X queries cost 2
(`docs/API_KEYS.md`, warning dated 27 oct: *"no actives `XPOZ_LIVE_ENABLED` sin recargar o usar
`XPOZ_API_KEY_2`"*), and `XPOZ_RUN_CREDIT_BUDGET` is also unset → default cap 12 credits/run.

**Consequence:** every tool that reads X live (`check_niche_trends`,
`discover_and_extract_niche_frameworks`, …) fails with `LiveDisabled` while the flag is off —
that is why the frameworks run in the UI reported *Failed*.

### "Did you try to rotate the keys? The one that you have?"

Yes — both keys were tested live today (the only way to test them; see the balance note below):

| key | call | result |
|---|---|---|
| `XPOZ_API_KEY` | `GET /api/data/twitter/posts/live?q=buildinpublic` | **200** — real posts returned (2 credits) |
| `XPOZ_API_KEY_2` | same | **200** — real posts returned (2 credits) |

**Both keys are alive.** Rotation itself is already implemented: the client rotates
`XPOZ_API_KEY` → `XPOZ_API_KEY_2` on **401/402/403** and a rotation inside one call is not
charged twice (`clients/xpoz.py:9-10,48,230`). Total spend for this audit: **4 credits**.

*Balance caveat:* there is no API-key-authenticated balance endpoint. The zero-credit routes
(`GET /api/plan`, `GET /api/usage`) answered **401 for both keys** — they need a dashboard
session JWT, not an API key (confirmed against docs.xpoz.ai). Remaining balance is only visible
in the Xpoz dashboard (https://www.xpoz.ai), or via the MCP `getAccountDetails` tool.

### "The Chroma too?"

**Chroma is fine.** `check_keys`: `OK chroma — Chroma Cloud respondió (heartbeat)`.
`.env` carries `CHROMA_API_KEY/TENANT/DATABASE=Lumi-Dev` plus `CHROMA_PATH` as the local
fallback, and the embedder (`onnx-minilm-l6-v2`, ~79 MB) is local and needs no key.
`MVP_CHROMA_*` is absent, which only affects the legacy handle-search MVP, not the app.
If a run ever reports `chroma_unavailable`, it is a runtime/network outage, not a key problem.

### "What other keys are not fully working?"

| service | status today | evidence |
|---|---|---|
| `OPENROUTER_API_KEY` | **BROKEN — 401 "User not found"** | `check_keys` + the live LLM traceback (`openai.AuthenticationError 401`) |
| `PFM_JWT_TOKEN` | **BROKEN — expired (401)** | `check_keys`: *PFM rechazó el token*; `docs/API_KEYS.md` warning 27 oct |
| Groq (`GROQ_API_KEY`) | works, but **rate-limited now**: `gpt-oss-120b` → 429, `qwen3.8-27b` → 413 too_large | backend traceback, today |
| Xpoz | keys **OK**, live calls **off** (`XPOZ_LIVE_ENABLED` unset) | section above |
| Meta, Google, Typesafe, DB, secret, token-encryption | **OK** | `check_keys` |
| LinkedIn, X | not probeable without a user / without spending | by design; LinkedIn validates at connect time |
| `OPENLUX_API_KEY`, `NEATLOGS_API_KEY`, `VIDEO_PROVIDER/VIDEO_API_KEY` | **absent** (optional services) | `check_keys`: OMITIDA |

**The worst one is OpenRouter, and it just cost us a chat turn:** the model chain is
Groq → Groq → OpenRouter, so when Groq 429'd, the fallback hit the dead OpenRouter key and the
whole run died with `AllProvidersFailed: groq rate_limit 429; groq too_large 413; openrouter auth 401`.

---

## 2. Remediation plan (ordered)

**P0 — make Xpoz live (needs your go-ahead: it spends credits).**
Add to `lumi/.env`:
```
XPOZ_LIVE_ENABLED=true
XPOZ_RUN_CREDIT_BUDGET=6      # 3 X queries per run; default 12 = 6 queries
```
Then `check_keys` + one `check_niche_trends` in the UI. Both keys are confirmed working, and
rotation to key 2 is automatic, so this is safe until the dashboard shows the balance low again.

**P1 — replace or remove `OPENROUTER_API_KEY`.**
It is the chain's fallback and it is dead: either issue a new key at openrouter.ai and rotate the
value in `.env`, or delete the line so the chain fails over to something that can work. This is the
difference between *one provider hiccup* and *a dead chat turn*.

**P2 — fix the Groq chain.**
`qwen3.8-27b` answers **413 too_large** for these payloads (it should be dropped or moved last) and
`gpt-oss-120b` is 429-throttled. Check `GROQ_MODEL_*` in `.env`/`lumi_ai/config.py` and keep at
least two *distinct* working models so a rate limit never ends a run.

**P3 — renew `PFM_JWT_TOKEN`** (ask Christian, per `docs/AGENT_KEYS_SETUP.md`).
Note this becomes moot with **P2 of the publish plan**: once native own-posts ingestion lands,
PFM leaves the read path entirely, so it may be worth letting it lapse instead of renewing.

**P4 — optional keys, only if you want the service:** `OPENLUX_*`, `NEATLOGS_*`, `VIDEO_*`.

**P5 — leave `X_LIVE_ENABLED=true` as is, deliberately.** Real X publishes cost
$0.015/post ($0.20 with a link); nothing should flip it off without a decision.

**Never** commit `.env`; the port-3010 backup from today is `.env.bak-port-20261029` (untracked).
