import assert from "node:assert/strict";
import { test } from "node:test";
import {
  connectErrorMessage,
  googleScopeLabels,
  isLiveDisabled,
  parseConnectHandoff,
  parseConnectReturn,
  startConnectMessage,
  stripConnectHandoff,
  stripConnectReturn,
} from "../src/api/connections.ts";
import { ApiError } from "../src/api/http.ts";

test("parseConnectReturn reads ?connected= and ?error=", () => {
  assert.deepEqual(parseConnectReturn("?connected=meta"), { kind: "connected", provider: "meta" });
  assert.deepEqual(parseConnectReturn("?error=connections.access_denied"), {
    kind: "error",
    code: "connections.access_denied",
  });
  assert.equal(parseConnectReturn("?utm=1"), null);
  assert.equal(parseConnectReturn(""), null);
});

test("an error wins over connected when both are present", () => {
  assert.equal(parseConnectReturn("?connected=x&error=internal_error")?.kind, "error");
});

test("stripConnectReturn removes only the return params", () => {
  assert.equal(
    stripConnectReturn("http://localhost:3010/?connected=meta&tab=a#top"),
    "/?tab=a#top",
  );
  assert.equal(stripConnectReturn("http://localhost:3010/?error=x"), "/");
});

test("every documented ?error= code has its own sentence", () => {
  const known = [
    "connections.state_invalid",
    "connections.state_expired",
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

test("parseConnectHandoff reads the grant the public callback leaves in the fragment", () => {
  assert.deepEqual(parseConnectHandoff("#connect=meta&code=abc%2F1&state=st_1"), {
    provider: "meta",
    code: "abc/1",
    state: "st_1",
  });
  assert.equal(parseConnectHandoff("#connect=meta&code=abc"), null);
  assert.equal(parseConnectHandoff("#connect=pfm&code=a&state=b"), null);
  assert.equal(parseConnectHandoff("#connect=evil&code=a&state=b"), null);
  assert.equal(parseConnectHandoff(""), null);
});

test("a handoff is never read from the query string, so a crafted ?code= is ignored", () => {
  assert.equal(parseConnectHandoff("?connect=meta&code=a&state=b"), null);
});

test("stripConnectHandoff removes the grant and keeps unrelated fragment data", () => {
  assert.equal(
    stripConnectHandoff("http://localhost:3010/?tab=a#connect=meta&code=c&state=s"),
    "/?tab=a",
  );
  assert.equal(
    stripConnectHandoff("http://localhost:3010/#connect=meta&code=c&state=s&x=1"),
    "/#x=1",
  );
});
