import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  connectErrorMessage,
  finishConnect,
  getConnectionStatus,
  googleScopeLabels,
  isLiveDisabled,
  linkAccount,
  linkChoice,
  linkErrorMessage,
  parseCallbackLanding,
  startConnectMessage,
  syncPfm,
} from "../src/api/connections.ts";
import { ApiError } from "../src/api/http.ts";

test("every documented ?error= code has its own sentence", () => {
  const known = [
    "connections.state_invalid",
    "connections.state_expired",
    "connections.state_mismatch",
    "connections.access_denied",
    "connections.account_taken",
    "connections.no_accounts",
    "connections.pfm_failed",
    "connections.provider_rejected",
    "connections.unknown_provider",
    "upstream_error",
    "internal_error",
  ];
  const fallback = connectErrorMessage("something.new");
  for (const code of known) assert.notEqual(connectErrorMessage(code), fallback, code);
});

test("startConnectMessage names the missing variables", () => {
  const err = new ApiError(503, "not_configured", "x", { env_vars: ["META_APP_ID", "META_APP_SECRET"] });
  assert.match(startConnectMessage(err), /META_APP_ID, META_APP_SECRET/);
  assert.match(startConnectMessage(new ApiError(503, "not_configured", "x")), /no está configurado/);
});

test("X off is recognised and explained", () => {
  const err = new ApiError(409, "connections.live_disabled", "off");
  assert.equal(isLiveDisabled(err), true);
  assert.match(startConnectMessage(err), /X_LIVE_ENABLED/);
  assert.equal(isLiveDisabled(new Error("x")), false);
});

test("googleScopeLabels translates known scopes and keeps unknown ones", () => {
  assert.deepEqual(
    googleScopeLabels("https://www.googleapis.com/auth/documents other.scope"),
    ["Crear y editar Google Docs", "other.scope"],
  );
  assert.deepEqual(googleScopeLabels(null), []);
});

test("connectErrorMessage reads a bare contract code the same as the prefixed one", () => {
  assert.equal(connectErrorMessage("access_denied"), connectErrorMessage("connections.access_denied"));
  assert.notEqual(connectErrorMessage("access_denied"), connectErrorMessage("whatever"));
});

test("the callback page reads the code and state the provider put in the query", () => {
  assert.deepEqual(parseCallbackLanding("/connections/meta/callback", "?code=abc%2F1&state=st_1"), {
    kind: "grant",
    provider: "meta",
    code: "abc/1",
    state: "st_1",
  });
  assert.equal(parseCallbackLanding("/connections/x/callback/", "?code=a&state=b")?.kind, "grant");
});

test("a denial keeps the state so the server can burn it", () => {
  assert.deepEqual(
    parseCallbackLanding("/connections/linkedin/callback", "?error=access_denied&state=s"),
    { kind: "denied", provider: "linkedin", state: "s", error: "access_denied" },
  );
});

test("a landing without state, without code, or for an unknown provider is ignored", () => {
  assert.equal(parseCallbackLanding("/connections/meta/callback", "?code=a"), null);
  assert.equal(parseCallbackLanding("/connections/meta/callback", "?state=a"), null);
  assert.equal(parseCallbackLanding("/connections/evil/callback", "?code=a&state=b"), null);
  assert.equal(parseCallbackLanding("/connections/meta/complete", "?code=a&state=b"), null);
  assert.equal(parseCallbackLanding("/", "?code=a&state=b"), null);
  assert.equal(parseCallbackLanding("/settings", ""), null);
});

test("a grant is never read from the fragment", () => {
  assert.equal(parseCallbackLanding("/", "#connect=meta&code=a&state=b"), null);
});

test("Post for Me sends no state and only says whether it worked", () => {
  assert.deepEqual(parseCallbackLanding("/connections/pfm/callback", "?isSuccess=true&accountIds=sa_1"), {
    kind: "pfm",
    success: true,
  });
  assert.deepEqual(parseCallbackLanding("/connections/pfm/callback", "?isSuccess=false&error=x"), {
    kind: "pfm",
    success: false,
  });
});

test("a state started by another account has its own sentence", () => {
  assert.notEqual(
    connectErrorMessage("connections.state_mismatch"),
    connectErrorMessage("whatever"),
  );
});

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function record(body: unknown = { provider: "pfm", connected: true, accounts: [] }) {
  const calls: { url: string; method: string }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET" });
    return new Response(JSON.stringify(body), { status: 200 });
  }) as typeof fetch;
  return calls;
}

test("the PFM landing syncs with a POST, never with the status GET", async () => {
  const calls = record();
  const result = await finishConnect({ kind: "pfm", success: true });
  assert.deepEqual(result, { provider: "pfm", connected: true });
  assert.deepEqual(
    calls.map((c) => [c.method, new URL(c.url).pathname]),
    [["POST", "/api/v1/connections/pfm/sync"]],
  );
});

test("a failed PFM landing asks the server nothing", async () => {
  const calls = record();
  await assert.rejects(finishConnect({ kind: "pfm", success: false }), { code: "connections.pfm_failed" });
  assert.equal(calls.length, 0);
});

test("syncPfm is a POST and reading a status is a GET", async () => {
  const calls = record();
  await syncPfm();
  await getConnectionStatus("pfm");
  assert.deepEqual(
    calls.map((c) => [c.method, new URL(c.url).pathname]),
    [
      ["POST", "/api/v1/connections/pfm/sync"],
      ["GET", "/api/v1/connections/pfm/status"],
    ],
  );
});

test("linkChoice offers an account only where the server would accept it", () => {
  const profile = { id: 7, platform: "facebook" };
  const page = { platform: "facebook", status: "active", profile_id: null };
  assert.equal(linkChoice(page, profile), "available");
  assert.equal(linkChoice({ ...page, profile_id: 7 }, profile), "linked");
  assert.equal(linkChoice({ ...page, profile_id: 9 }, profile), "available");
  assert.equal(linkChoice({ ...page, platform: "instagram" }, profile), "other_network");
  assert.equal(linkChoice({ ...page, platform: null }, profile), "available");
  assert.equal(linkChoice({ ...page, status: "revoked" }, profile), "reconnect");
  assert.equal(linkChoice({ ...page, status: "error" }, profile), "reconnect");
  assert.equal(linkChoice({ ...page, status: "limited" }, profile), "available");
});

test("linkAccount posts the account and the profile and nothing else", async () => {
  const seen: { url: string; body: unknown; method: string }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    seen.push({ url: String(url), body: JSON.parse(String(init.body)), method: String(init.method) });
    return new Response(JSON.stringify({ provider: "meta", profile_id: 7 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  await linkAccount("meta", "1001", 7);
  assert.equal(seen.length, 1);
  assert.match(seen[0].url, /\/connections\/meta\/link$/);
  assert.equal(seen[0].method, "POST");
  assert.deepEqual(seen[0].body, { account_id: "1001", profile_id: 7 });
});

test("a refused link says why", () => {
  assert.match(linkErrorMessage(new ApiError(409, "connections.platform_mismatch", "x")), /otra red/);
  assert.match(linkErrorMessage(new ApiError(409, "connections.account_unusable", "x")), /reconect/);
  assert.match(linkErrorMessage(new Error("boom")), /No se pudo enlazar/);
});
