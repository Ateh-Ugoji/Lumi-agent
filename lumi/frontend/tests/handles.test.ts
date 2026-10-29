import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { getSavedHandles, searchHandles, selectHandle } from "../src/api/handles.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("selectHandle sends the handle and its own network, and nothing the server could store as someone's photo or numbers", async () => {
  const seen: { url: string; body: unknown; method: string }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    seen.push({ url: String(url), body: JSON.parse(String(init.body)), method: String(init.method) });
    return new Response(JSON.stringify({ remembered: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  await selectHandle({
    handle: "karpathy",
    display_name: "Andrej",
    avatar_url: "https://img.example/a.png",
    followers: 1200,
    platform: "instagram",
    source: "live",
  });
  assert.equal(seen.length, 1);
  assert.equal(seen[0].method, "POST");
  assert.equal(new URL(seen[0].url).pathname.endsWith("/handles/select"), true);
  assert.deepEqual(seen[0].body, { handle: "karpathy", platform: "instagram" });
});

test("a row without a platform is sent as X, the network the composer searches", async () => {
  const bodies: unknown[] = [];
  globalThis.fetch = (async (_url: string, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  await selectHandle({ handle: "karpathy" });
  assert.deepEqual(bodies, [{ handle: "karpathy", platform: "x" }]);
});

test("search and saved always name the network, because the server has no default", async () => {
  const urls: URL[] = [];
  globalThis.fetch = (async (url: string) => {
    urls.push(new URL(String(url)));
    return new Response(JSON.stringify({ query: "", results: [], live: false, refreshed: false }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  await searchHandles("naval", "follow");
  await getSavedHandles();
  assert.equal(urls.length, 2);
  assert.equal(urls[0].pathname.endsWith("/handles/search"), true);
  assert.deepEqual(Object.fromEntries(urls[0].searchParams), {
    q: "naval",
    context: "follow",
    platforms: "x",
  });
  assert.equal(urls[1].pathname.endsWith("/handles/saved"), true);
  assert.deepEqual(Object.fromEntries(urls[1].searchParams), { platforms: "x" });
});

test("selectHandle never throws when the server is down", async () => {
  globalThis.fetch = (async () => {
    throw new Error("offline");
  }) as typeof fetch;
  await selectHandle({ handle: "karpathy" });
});
