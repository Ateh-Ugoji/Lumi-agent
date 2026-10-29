import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  ApiError,
  buildUrl,
  clearToken,
  errorFromBody,
  onUnauthorized,
  readToken,
  request,
  writeToken,
  type KeyValueStore,
} from "../src/api/http.ts";

function memoryStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  };
}

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
  clearToken(null);
});

test("errorFromBody reads the contract error envelope", () => {
  const err = errorFromBody(
    503,
    JSON.stringify({ error: { code: "not_configured", message: "No keys", details: { env_vars: ["A"] } } }),
  );
  assert.equal(err.status, 503);
  assert.equal(err.code, "not_configured");
  assert.equal(err.message, "No keys");
  assert.deepEqual(err.details, { env_vars: ["A"] });
});

test("errorFromBody survives a body that is not JSON", () => {
  const err = errorFromBody(502, "<html>Bad gateway</html>");
  assert.equal(err.code, "http_error");
  assert.equal(err.message, "Lumi's server isn't responding. Try again in a moment.");
  assert.ok(!err.message.includes("<"), "an HTML page never reaches the user");
  assert.equal(errorFromBody(500, "<h1>Server Error</h1>").message, "Lumi's server had a problem. Try again in a moment.");
  assert.equal(errorFromBody(404, "<html>").message, "Error 404");
  assert.equal(errorFromBody(401, "").code, "unauthenticated");
});

test("buildUrl skips empty query values and keeps a single slash", () => {
  assert.equal(
    buildUrl("/profiles", { a: 1, b: "", c: undefined, d: null, e: false }, "http://x/api/v1"),
    "http://x/api/v1/profiles?a=1&e=false",
  );
  assert.equal(buildUrl("profiles", undefined, "http://x/api/v1"), "http://x/api/v1/profiles");
});

test("the token store round-trips and tolerates a missing store", () => {
  const store = memoryStore();
  assert.equal(readToken(store), null);
  writeToken("abc", store);
  assert.equal(readToken(store), "abc");
  clearToken(store);
  assert.equal(readToken(store), null);
  assert.equal(readToken(null), null);
});

test("request sends the Token header and parses JSON", async () => {
  writeToken("tok-1", null); // no store in node: kept in memory
  let seen: { url: string; init: RequestInit } | null = null;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    seen = { url, init };
    return new Response(JSON.stringify({ ok: 1 }), { status: 200 });
  }) as typeof fetch;
  const out = await request<{ ok: number }>("/profiles", { query: { a: 1 } });
  assert.deepEqual(out, { ok: 1 });
  assert.ok(seen);
  const { url, init } = seen as { url: string; init: RequestInit };
  assert.match(url, /\/api\/v1\/profiles\?a=1$/);
  assert.equal((init.headers as Record<string, string>).Authorization, "Token tok-1");
});

test("public routes send no token and a 204 resolves to undefined", async () => {
  writeToken("tok-1", null);
  let headers: Record<string, string> = {};
  globalThis.fetch = (async (_u: string, init: RequestInit) => {
    headers = init.headers as Record<string, string>;
    return new Response(null, { status: 204 });
  }) as typeof fetch;
  assert.equal(await request("/auth/login", { method: "POST", body: {}, auth: false }), undefined);
  assert.equal(headers.Authorization, undefined);
  assert.equal(headers["Content-Type"], "application/json");
});

test("a 401 on an authenticated request clears the token and notifies once", async () => {
  writeToken("tok-1", null);
  let notified = 0;
  const off = onUnauthorized(() => void (notified += 1));
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ error: { code: "unauthenticated", message: "no" } }), {
      status: 401,
    })) as typeof fetch;
  await assert.rejects(request("/profiles"), (e: unknown) => e instanceof ApiError && e.status === 401);
  assert.equal(notified, 1);
  // a failed login (public) must not log anybody out
  await assert.rejects(request("/auth/login", { method: "POST", auth: false }));
  assert.equal(notified, 1);
  off();
});

test("a network failure becomes a readable ApiError", async () => {
  globalThis.fetch = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  await assert.rejects(request("/profiles"), (e: unknown) => e instanceof ApiError && e.code === "network_error");
});
