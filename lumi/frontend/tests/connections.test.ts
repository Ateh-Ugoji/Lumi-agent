import assert from "node:assert/strict";
import { test } from "node:test";
import {
  connectErrorMessage,
  googleScopeLabels,
  isLiveDisabled,
  parseCallbackLanding,
  startConnectMessage,
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
