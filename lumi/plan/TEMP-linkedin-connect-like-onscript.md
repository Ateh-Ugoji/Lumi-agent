# TEMP — LinkedIn connect: confirm the handover message and reach Onscript parity

Status: **research + plan. No code needed for parity — the flow already matches Onscript.**
Written 2026-10-28 on branch `Ateh-branch`, from `lumi-orquestador` + `webappv2-github` (Onscript).

## 1. The direct answer: do users bring an API key?

**No — in neither app.** Both apps hold the LinkedIn OAuth client credentials on the
server; the user only clicks *Connect* and signs in to LinkedIn:

| | Onscript (`webappv2-github`) | Lumi (`lumi-orquestador`) |
|---|---|---|
| Keys live | backend env `LINKEDIN_CLIENT_ID=…` (`CONNECT_SOCIAL_BREAKDOWN.md:1966`) | `lumi/.env` `LINKEDIN_CLIENT_ID/SECRET` (wired in P0, 2026-10-28) |
| User clicks | Connect → `GET /integrations/linkedin/oauth/initiate` → `{auth_url}` → consent screen | Connect → `POST /api/v1/connections/linkedin/connect` → `{authorize_url}` → consent screen (`frontend/src/api/connections.ts:52`) |
| Redirect back | `/integrations/linkedin/oauth/callback?code&state` → backend exchanges | `/connections/<provider>/callback` (frontend route, `api/connections.ts:141`, `App.tsx:390`) → backend exchanges, stores tokens |
| Scopes requested | `openid profile email w_member_social` (`LINKEDIN_SCOPES`) | `openid profile email w_member_social` (`apps/connections/providers/linkedin.py:52`, joined into the authorize URL at `:115`) — **identical** |
| Publishes as | `urn:li:person:{id}` (UGC posts) | `urn:li:person:{id}` (`linkedin.py:223,268`) — **identical, personal profile** |
| PKCE for LinkedIn | none | none (`uses_pkce=False`, `linkedin.py:95`) |
| User ever pastes a key | never | never |

**Verdict: Lumi's connect is architecturally the same as Onscript's already** — one click,
server-held credentials, sign-in on LinkedIn's own page. What differs is only *setup state*:
Onscript's app is registered and approved; ours needs the portal steps in §3.

## 2. Confirming the handover message, point by point

| Claim | Verdict | Evidence |
|---|---|---|
| "Add `http://localhost:3010/connections/linkedin/callback`" | ✅ **Correct — matches this checkout** | `FRONTEND_URL=http://localhost:3010` in `lumi/.env` (aligned 2026-10-28; it previously said 3011, which is what an explicit `vite --port 3011` startup used). `config.redirect_uri()` (`apps/connections/config.py:185-188`) builds `{FRONTEND_URL}/connections/{provider}/callback`, so the app now sends **3010** — the same port `npm run dev` serves (`vite --port 3010`). Register **3010**; adding 3011 as an alias too is harmless (LinkedIn accepts a list), but the invariant that matters is: **`FRONTEND_URL` must equal the port Vite actually serves** (CORS already allows both). |
| "Permissions: openid, profile, email and w_member_social" | ✅ Correct, exactly | `linkedin.py:52` `SCOPES = ("openid", "profile", "email", "w_member_social")`, used verbatim in the authorize URL (`:115`). Also identical to Onscript's `LINKEDIN_SCOPES`. |
| "Confirm the app has them enabled" | ✅ Required step | Portal → app → **Products**: "Sign In with LinkedIn using OpenID Connect" (provides openid/profile/email) + "Share on LinkedIn" (provides w_member_social). Without the products, LinkedIn drops the scopes or rejects the request. |
| "This connection is personal… one individual, not a company page" | ✅ Correct, and enforced by the code | Publish uses `urn:li:person:{id}` (`linkedin.py:223,268`). Company-page publishing needs the **Community Management API** (`urn:li:organization` + `w_organization_social`) — not implemented, not requested, out of scope. |
| "You (the owner) must complete the sign-in" | ✅ Correct | Whoever clicks Connect and approves on LinkedIn becomes the connected profile. A dev clicking it connects the **dev's own** LinkedIn, and every later publish goes out as that person. |
| "Publishing as a company page would need the Community Management API" | ✅ Correct | Separate LinkedIn product + organization URN + different scopes; would be a new provider capability (P6-style), not a tweak. |

## 3. The plan — reach parity with Onscript's connect

Ordered; each step says who does it and how it is verified.

### L1. Register the redirect URL (human, ~2 min, portal only)
LinkedIn Developer Portal → our app → **Auth** → *Authorized redirect URLs* → add:
- `http://localhost:3010/connections/linkedin/callback` (the one the code sends — **required**)
- `http://localhost:3011/connections/linkedin/callback` (alias, only useful if you serve Vite on
  3011 — then also flip `FRONTEND_URL` to 3011; the two must always match)

### L2. Confirm products + scopes (human, portal only)
**Products** tab: "Sign In with LinkedIn using OpenID Connect" and "Share on LinkedIn" both
*Added*. Then **Auth** shows the allowed scopes; `w_member_social` must be among them.

### L3. Connect as the owner (human, ~2 min)
Start `lumi` (backend :8001 + frontend :3010 via `npm run dev`), open **Settings → Connected Accounts →
LinkedIn → Connect**, sign in with the owner's LinkedIn credentials, approve the four
permissions. The dev does not do this step with their own account.

### L4. Verify end to end (code/commands)
1. `manage.py check_keys --only linkedin` → `linkedin OK`.
2. `GET /api/v1/connections/linkedin/status` → `configured: true`, `connected: true`,
   details carry `w_member_social` in the granted scopes (never token values).
3. Publish screen → dry-run publish to LinkedIn → 200 preview, nothing sent
   (`dry_run`); a real publish only with the owner's explicit permission (protocol).
4. Negative check: a redirect URI that does not match `FRONTEND_URL` exactly (wrong port,
   trailing slash, https vs http) → LinkedIn rejects with `redirect_uri_mismatch` — that is
   the failure mode L1 prevents.

### L5. Decide the read scope for P2 (owner decision, not needed for connect)
Lumi's OAuth request does **not** include `r_member_social` (reads), so a freshly
connected account reports `limited` for reads and the agent says so honestly
(`linkedin.py:92-95,201-211`). For P2 (native LinkedIn own-posts reading) we must ask
`r_member_social` in the authorize URL — it is a **restricted scope** (LinkedIn app
review). Options: (a) request it now alongside the four, (b) ship connect+publish now,
request reads later. **Recommendation: (b)** — connect/publish (the user-visible feature)
is unblocked today; review takes days and blocks nothing.

### L6. Before production deploy (human + docs)
Register the production callback `{PROD_URL}/connections/linkedin/callback` (Railway/webapp
domain) in the same portal page; update `docs/CONEXIONES.md` and `docs/API_KEYS.md` with the
final URL list. Same rule applies to X/Meta/Google portals (P0 note).

## 4. What is NOT in scope

- Company-page publishing (Community Management API) — separate product + review.
- Changing the OAuth flow itself — it already matches Onscript; no refactor.
- Onscript-only extras (TanStack route structure, undici IPv4 dispatcher) — internal to
  that codebase; Lumi's httpx path has no known LinkedIn-specific issue. If the token
  exchange ever fails with an odd network error, revisit the IPv4 note
  (`CONNECT_SOCIAL_BREAKDOWN.md:1609-1620`).
